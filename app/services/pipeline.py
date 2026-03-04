"""LangGraph-based agent orchestration: EXTRACT → VALIDATE → CORRECT → FINALIZE → LOG.

Uses a LangGraph StateGraph so the self-correction cycle is modelled as a
directed graph with conditional edges, matching the system design diagram.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Attempt, Job, JobStatus, ValidationStatus
from app.llm.client import call_llm
from app.llm.prompts import build_correction_prompt, build_extraction_prompt
from app.schemas.data_schemas import get_schema_class
from app.services.dedup import cache_completed_job
from app.services.distributed_controls import (
    consume_retry_budget,
    record_job_start,
    record_retry_attempt,
    should_use_fallback_model,
)
from app.services.validator import validate_against_schema
from app.utils.logging import metrics

logger = logging.getLogger(__name__)
settings = get_settings()


# ═══════════════════════════════════════════════════════════════════════
# LangGraph state schema
# ═══════════════════════════════════════════════════════════════════════

class PipelineState(TypedDict, total=False):
    """Shared state passed between LangGraph nodes."""
    job_id: str
    raw_text: str
    schema_name: str | None
    api_key_id: str | None  # For per-tenant budget tracking
    attempt_number: int
    previous_json: str | None
    validation_errors: str | None
    final_data: dict[str, Any] | None
    is_valid: bool
    error: str | None
    # Internal transport (prefixed with _)
    _parsed: dict | None
    _llm_resp: Any
    _prompt: str


# ═══════════════════════════════════════════════════════════════════════
# Graph node functions
# ═══════════════════════════════════════════════════════════════════════

async def extract_node(state: PipelineState) -> dict:
    """State 1 – Initial LLM extraction (Gemini Flash)."""
    schema_cls = get_schema_class(state.get("schema_name"))
    prompt = build_extraction_prompt(state["raw_text"], schema_cls)
    llm_resp = await call_llm(prompt)

    metrics.record_tokens(llm_resp.tokens_used)
    metrics.record_latency(llm_resp.latency_ms)

    if llm_resp.error and llm_resp.parsed_json is None:
        metrics.record_validation_failure()
        return {
            "previous_json": llm_resp.raw_text,
            "validation_errors": llm_resp.error,
            "is_valid": False,
            "_llm_resp": llm_resp,
            "_prompt": prompt,
            "_parsed": None,
        }

    parsed = llm_resp.parsed_json or {}
    return {
        "previous_json": json.dumps(parsed, indent=2),
        "is_valid": False,
        "_parsed": parsed,
        "_llm_resp": llm_resp,
        "_prompt": prompt,
    }


async def validate_node(state: PipelineState) -> dict:
    """State 2 – Validate parsed JSON against the Pydantic schema."""
    parsed = state.get("_parsed")
    if parsed is None:
        # LLM returned garbage / error — keep existing validation_errors
        return {
            "is_valid": False,
            "validation_errors": state.get("validation_errors", "LLM did not return valid JSON"),
        }

    schema_cls = get_schema_class(state.get("schema_name"))
    result = validate_against_schema(parsed, schema_cls)

    if result.is_valid:
        return {"is_valid": True, "final_data": result.data, "validation_errors": None}

    metrics.record_validation_failure()
    return {
        "is_valid": False,
        "validation_errors": result.error_summary,
        "previous_json": json.dumps(parsed, indent=2),
    }


async def correct_node(state: PipelineState) -> dict:
    """State 3 – Self-correction: re-prompt LLM with validation errors.

    Checks per-tenant AND global retry budget before making LLM call.
    Uses fallback model when degradation detected or for retry cost savings.
    """
    api_key_id = state.get("api_key_id")
    
    # Record retry attempt for degradation tracking
    await record_retry_attempt()
    
    # Check and consume distributed retry budget (per-key + global)
    budget_allowed, remaining_budget, rejection_reason = await consume_retry_budget(
        budget_per_hour=settings.retry_budget_per_hour,
        window_seconds=3600,
        api_key_id=api_key_id,
        per_key_budget=settings.per_key_retry_budget_per_hour if api_key_id else None,
    )
    if not budget_allowed:
        reason_msg = (
            "Per-tenant retry budget exhausted" 
            if rejection_reason == "PER_KEY_BUDGET_EXHAUSTED" 
            else "Global retry budget exhausted"
        )
        logger.warning("%s, skipping LLM correction", reason_msg)
        return {
            "attempt_number": settings.max_retries,  # Force exit from retry loop
            "validation_errors": reason_msg,
            "is_valid": False,
            "_llm_resp": None,
            "_prompt": "",
            "_parsed": None,
            "error": rejection_reason or "RETRY_BUDGET_EXHAUSTED",
        }
    logger.debug("Retry budget consumed, remaining this hour: %d", remaining_budget)

    schema_cls = get_schema_class(state.get("schema_name"))
    attempt = state.get("attempt_number", 0) + 1

    prompt = build_correction_prompt(
        state["raw_text"],
        state.get("previous_json") or "",
        state.get("validation_errors") or "",
        schema_cls,
    )
    
    # Determine model: use fallback if degradation detected OR if configured for retries
    fallback_model = None
    use_fallback = await should_use_fallback_model() or settings.use_fallback_for_retries
    if use_fallback:
        if settings.llm_provider.value == "openai":
            fallback_model = settings.openai_fallback_model
        else:
            fallback_model = settings.gemini_fallback_model
        logger.debug(f"Using fallback model for correction: {fallback_model}")
    
    llm_resp = await call_llm(prompt, model_override=fallback_model)

    metrics.record_tokens(llm_resp.tokens_used)
    metrics.record_latency(llm_resp.latency_ms)
    metrics.record_retry()

    if llm_resp.error and llm_resp.parsed_json is None:
        metrics.record_validation_failure()
        return {
            "attempt_number": attempt,
            "previous_json": llm_resp.raw_text,
            "validation_errors": llm_resp.error,
            "is_valid": False,
            "_llm_resp": llm_resp,
            "_prompt": prompt,
            "_parsed": None,
        }

    parsed = llm_resp.parsed_json or {}
    return {
        "attempt_number": attempt,
        "previous_json": json.dumps(parsed, indent=2),
        "is_valid": False,
        "_parsed": parsed,
        "_llm_resp": llm_resp,
        "_prompt": prompt,
    }


async def finalize_node(state: PipelineState) -> dict:
    """State 4 – Finalization (marker node; DB writes in runner)."""
    return {}


async def log_node(state: PipelineState) -> dict:
    """State 5 – Logging + Storage (marker node; DB writes in runner)."""
    return {}


# ═══════════════════════════════════════════════════════════════════════
# Conditional routing
# ═══════════════════════════════════════════════════════════════════════

def after_validate(state: PipelineState) -> str:
    """Route: if valid → finalize, elif retries left → correct, else → finalize."""
    if state.get("is_valid"):
        return "finalize"
    if state.get("attempt_number", 0) >= settings.max_retries:
        return "finalize"
    return "correct"


# ═══════════════════════════════════════════════════════════════════════
# Build & compile the LangGraph StateGraph
# ═══════════════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """Construct the self-correcting validation graph.

    Graph topology:
        extract → validate ─┬─ (valid)      → finalize → log → END
                             ├─ (retries ok) → correct  → validate (loop)
                             └─ (exhausted)  → finalize → log → END
    """
    graph = StateGraph(PipelineState)

    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_node)
    graph.add_node("correct", correct_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("log", log_node)

    graph.set_entry_point("extract")
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges("validate", after_validate, {
        "finalize": "finalize",
        "correct": "correct",
    })
    graph.add_edge("correct", "validate")
    graph.add_edge("finalize", "log")
    graph.add_edge("log", END)

    return graph.compile()


# Compile once at module level
_compiled_graph = build_graph()


# ═══════════════════════════════════════════════════════════════════════
# Pipeline runner  (DB-aware wrapper around the LangGraph)
# ═══════════════════════════════════════════════════════════════════════

async def _check_job_cancelled(session: AsyncSession, job_id: str) -> bool:
    """Check if a job has been cancelled or timed out."""
    await session.refresh(await session.get(Job, job_id))
    job = await session.get(Job, job_id)
    if job is None:
        return True
    return job.status in (JobStatus.CANCELLED.value, JobStatus.TIMEOUT.value)


async def run_pipeline(job_id: str, session: AsyncSession) -> None:
    """Execute the LangGraph pipeline and persist every step to the DB.

    Called from a FastAPI background task – never raises.
    Checks for cancellation before each major step.
    """
    job = await session.get(Job, job_id)
    if job is None:
        logger.error("Job %s not found", job_id)
        return

    # Check if already cancelled before starting
    if job.status in (JobStatus.CANCELLED.value, JobStatus.TIMEOUT.value):
        logger.info("Job %s already %s, skipping", job_id, job.status)
        return

    raw_text: str = job.raw_input
    schema_name: str | None = job.schema_name

    initial_state: PipelineState = {
        "job_id": job_id,
        "raw_text": raw_text,
        "schema_name": schema_name,
        "api_key_id": job.api_key_id,  # For per-tenant budget tracking
        "attempt_number": 0,
        "previous_json": None,
        "validation_errors": None,
        "final_data": None,
        "is_valid": False,
        "error": None,
    }

    try:
        # Record job start for degradation tracking
        await record_job_start()
        
        job.status = JobStatus.EXTRACTING.value
        await session.commit()

        current_state: dict = dict(initial_state)

        # ── Stream through LangGraph nodes ───────────────────────────
        async for event in _compiled_graph.astream(initial_state):
            # Check for cancellation before processing each node
            if await _check_job_cancelled(session, job_id):
                logger.info("Job %s cancelled during processing", job_id)
                return

            if not isinstance(event, dict):
                continue
            for node_name, node_output in event.items():
                if not isinstance(node_output, dict):
                    continue
                current_state.update(node_output)
                logger.info(
                    "Job %s | Node: %s | attempt=%d",
                    job_id, node_name, current_state.get("attempt_number", 0),
                )

                # Update DB job status
                status_map = {
                    "extract": JobStatus.EXTRACTING,
                    "validate": JobStatus.VALIDATING,
                    "correct": JobStatus.CORRECTING,
                    "finalize": JobStatus.FINALIZING,
                }
                if node_name in status_map:
                    job.status = status_map[node_name].value
                    await session.commit()

                # Persist LLM attempts (extract / correct nodes)
                if node_name in ("extract", "correct"):
                    llm_resp = current_state.get("_llm_resp")
                    prompt = current_state.get("_prompt", "")
                    parsed = current_state.get("_parsed")

                    attempt_rec = Attempt(
                        job_id=job_id,
                        attempt_number=current_state.get("attempt_number", 0),
                        prompt_sent=prompt,
                        llm_response=llm_resp.raw_text if llm_resp else "",
                        parsed_json=json.dumps(parsed) if parsed else None,
                        tokens_used=llm_resp.tokens_used if llm_resp else 0,
                        latency_ms=llm_resp.latency_ms if llm_resp else 0.0,
                    )

                    if llm_resp:
                        job.total_tokens += llm_resp.tokens_used
                        job.total_latency_ms += llm_resp.latency_ms

                    # Store reference so validate can tag it
                    current_state["_last_attempt"] = attempt_rec

                # After validation, finalise the most recent attempt record
                if node_name == "validate":
                    last_att = current_state.get("_last_attempt")
                    if last_att is not None:
                        last_att.is_valid = current_state.get("is_valid", False)
                        last_att.validation_errors = current_state.get("validation_errors")
                        session.add(last_att)
                        await session.commit()

        # ── FINALIZE ─────────────────────────────────────────────────
        is_valid = current_state.get("is_valid", False)
        final_data = current_state.get("final_data")
        attempt_number = current_state.get("attempt_number", 0)

        if is_valid and final_data is not None:
            job.structured_output = json.dumps(final_data)
            job.validation_status = ValidationStatus.VALID.value
            job.status = JobStatus.COMPLETED.value
            # Cache for input deduplication
            if job.input_hash:
                await cache_completed_job(job.input_hash, job.id)
        else:
            job.validation_status = ValidationStatus.INVALID.value
            job.status = JobStatus.FAILED.value
            job.error_message = (
                f"Validation failed after {attempt_number} correction(s). "
                f"Last errors:\n{current_state.get('validation_errors', 'Unknown')}"
            )

        job.retry_count = attempt_number

        # ── LOG ──────────────────────────────────────────────────────
        logger.info(
            "Job %s | State: LOG | status=%s | retries=%d | tokens=%d | latency=%.0fms",
            job_id, job.status, job.retry_count,
            job.total_tokens, job.total_latency_ms,
        )

        await session.commit()

    except Exception as exc:
        logger.exception("Job %s | Unhandled error in pipeline", job_id)
        job.status = JobStatus.FAILED.value
        job.error_message = f"Pipeline error: {exc}"
        await session.commit()
