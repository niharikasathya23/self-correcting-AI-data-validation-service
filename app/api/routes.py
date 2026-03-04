"""API router – /process and /result endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFoundError
from app.core.config import get_settings
from app.db.models import Attempt, Job, JobStatus, OutboxEvent, OutboxEventType
from app.db.session import async_session_factory, get_db
from app.schemas.api_models import (
    AttemptDetail,
    ProcessRequest,
    ProcessResponse,
    ResultResponse,
)
from app.services.pipeline import run_pipeline
from app.services.distributed_controls import (
    get_retry_budget_status_distributed,
    get_degradation_status,
)
from app.utils.logging import metrics
from app.api.security import check_rate_limit

router = APIRouter()
settings = get_settings()


# ═══════════════════════════════════════════════════════════════════════
# Background task wrapper
# ═══════════════════════════════════════════════════════════════════════

async def _run_pipeline_bg(job_id: str) -> None:
    """Run the pipeline inside its own DB session (background safe)."""
    async with async_session_factory() as session:
        await run_pipeline(job_id, session)


# ═══════════════════════════════════════════════════════════════════════
# POST /process
# ═══════════════════════════════════════════════════════════════════════

@router.post("/process", response_model=ProcessResponse, status_code=202)
async def process_text(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key_id: str = Depends(check_rate_limit),
    idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
) -> ProcessResponse:
    """Accept raw text, create a job, and launch background processing.

    When USE_REDIS_QUEUE=true, the job is pushed to Redis for a worker
    to pick up.  Otherwise it runs in a FastAPI BackgroundTask (default).

    Identical inputs (SHA-256 match) return the previous completed job
    instantly, avoiding redundant LLM spend.

    X-Idempotency-Key header: If provided, ensures the same job is returned
    for retried requests (prevents duplicate processing).
    """
    from app.services.dedup import compute_input_hash, find_duplicate_job

    # ── Idempotency key check ────────────────────────────────────────
    if idempotency_key:
        stmt = select(Job).where(Job.idempotency_key == idempotency_key)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return ProcessResponse(
                job_id=existing.id,
                status=existing.status,
                message="Request with this idempotency key already processed.",
            )

    input_hash = compute_input_hash(body.raw_text, body.schema_name)

    # ── Deduplication check ──────────────────────────────────────────
    existing_job_id = await find_duplicate_job(input_hash, db)
    if existing_job_id:
        return ProcessResponse(
            job_id=existing_job_id,
            status="COMPLETED",
            message="Duplicate input detected – returning cached result.",
        )

    job = Job(
        raw_input=body.raw_text,
        schema_name=body.schema_name,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
        api_key_id=api_key_id,  # Store for per-tenant budget tracking
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    await db.flush()
    
    # ── Transactional Outbox Pattern ─────────────────────────────────
    # Write Job + OutboxEvent in the SAME transaction to ensure atomicity.
    # A separate dispatcher reads the outbox and enqueues to Redis.
    if settings.use_redis_queue:
        outbox_event = OutboxEvent(
            event_type=OutboxEventType.ENQUEUE_JOB.value,
            payload=json.dumps({"job_id": job.id, "schema_name": body.schema_name}),
            job_id=job.id,
        )
        db.add(outbox_event)
        message = "Job created and queued for dispatch to Redis."
    
    await db.commit()
    await db.refresh(job)

    # For non-Redis mode, still use background tasks (no outbox needed)
    if not settings.use_redis_queue:
        background_tasks.add_task(_run_pipeline_bg, job.id)
        message = "Job enqueued for processing."

    return ProcessResponse(
        job_id=job.id,
        status=job.status,
        message=message,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /result/{job_id}
# ═══════════════════════════════════════════════════════════════════════

@router.get("/result/{job_id}", response_model=ResultResponse)
async def get_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> ResultResponse:
    """Return the current state / final result of a job."""
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)

    # Fetch all attempts for the correction log
    stmt = (
        select(Attempt)
        .where(Attempt.job_id == job_id)
        .order_by(Attempt.attempt_number)
    )
    result = await db.execute(stmt)
    attempts = result.scalars().all()

    correction_log = []
    for a in attempts:
        parsed: dict[str, Any] | None = None
        if a.parsed_json:
            try:
                parsed = json.loads(a.parsed_json)
            except json.JSONDecodeError:
                parsed = None
        correction_log.append(
            AttemptDetail(
                attempt_number=a.attempt_number,
                llm_response=a.llm_response,
                parsed_json=parsed,
                validation_errors=a.validation_errors,
                is_valid=a.is_valid,
                tokens_used=a.tokens_used,
                latency_ms=a.latency_ms,
                created_at=a.created_at,
            )
        )

    structured: dict[str, Any] | None = None
    if job.structured_output:
        try:
            structured = json.loads(job.structured_output)
        except json.JSONDecodeError:
            structured = None

    # Calculate backoff hints for polling clients
    terminal_statuses = {
        JobStatus.COMPLETED.value, JobStatus.FAILED.value,
        JobStatus.TIMEOUT.value, JobStatus.CANCELLED.value
    }
    is_terminal = job.status in terminal_statuses
    
    # Suggest retry interval based on job state
    if is_terminal:
        retry_after = None  # No need to poll again
    elif job.status == JobStatus.PENDING.value:
        retry_after = 2  # Quick initial check
    elif job.status in (JobStatus.EXTRACTING.value, JobStatus.VALIDATING.value):
        retry_after = 3  # Active processing
    elif job.status == JobStatus.CORRECTING.value:
        retry_after = 5  # Correction takes longer
    else:
        retry_after = 5  # Default

    return ResultResponse(
        job_id=job.id,
        status=job.status,
        validation_status=job.validation_status,
        retry_count=job.retry_count,
        structured_output=structured,
        error_message=job.error_message,
        correction_log=correction_log,
        total_tokens=job.total_tokens,
        total_latency_ms=job.total_latency_ms,
        created_at=job.created_at,
        updated_at=job.updated_at,
        retry_after_seconds=retry_after,
        is_terminal=is_terminal,
    )


# ═══════════════════════════════════════════════════════════════════════
# POST /cancel/{job_id}
# ═══════════════════════════════════════════════════════════════════════

@router.post("/cancel/{job_id}")
async def cancel_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    api_key_id: str = Depends(check_rate_limit),
) -> dict:
    """Cancel a pending or in-progress job."""
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)

    # Can only cancel jobs that aren't already terminal
    terminal_statuses = {JobStatus.COMPLETED.value, JobStatus.FAILED.value,
                         JobStatus.TIMEOUT.value, JobStatus.CANCELLED.value}
    if job.status in terminal_statuses:
        return {
            "job_id": job_id,
            "status": job.status,
            "message": f"Job already in terminal state: {job.status}",
            "cancelled": False,
        }

    job.status = JobStatus.CANCELLED.value
    job.error_message = "Cancelled by user request"
    await db.commit()

    return {
        "job_id": job_id,
        "status": job.status,
        "message": "Job cancelled successfully",
        "cancelled": True,
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /cleanup-timeouts  (admin endpoint)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/cleanup-timeouts")
async def cleanup_timeout_jobs(
    db: AsyncSession = Depends(get_db),
    api_key_id: str = Depends(check_rate_limit),
) -> dict:
    """Mark stale jobs as TIMEOUT. Call periodically or on-demand."""
    from datetime import datetime, timedelta, timezone

    timeout_threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.job_timeout_seconds)

    # Find jobs stuck in non-terminal states past the timeout
    non_terminal = [
        JobStatus.PENDING.value, JobStatus.EXTRACTING.value,
        JobStatus.VALIDATING.value, JobStatus.CORRECTING.value,
        JobStatus.FINALIZING.value,
    ]

    stmt = select(Job).where(
        Job.status.in_(non_terminal),
        Job.created_at < timeout_threshold,
    )
    result = await db.execute(stmt)
    stale_jobs = result.scalars().all()

    count = 0
    for job in stale_jobs:
        job.status = JobStatus.TIMEOUT.value
        job.error_message = f"Job exceeded timeout of {settings.job_timeout_seconds}s"
        count += 1

    await db.commit()

    return {
        "cleaned_up": count,
        "timeout_seconds": settings.job_timeout_seconds,
        "message": f"Marked {count} stale job(s) as TIMEOUT",
    }


# ═══════════════════════════════════════════════════════════════════════
# Dead Letter Queue (DLQ) – failed/timeout jobs
# ═══════════════════════════════════════════════════════════════════════

DLQ_STATUSES = {JobStatus.FAILED.value, JobStatus.TIMEOUT.value}


@router.get("/dlq")
async def list_dlq_jobs(
    db: AsyncSession = Depends(get_db),
    api_key_id: str = Depends(check_rate_limit),
    limit: int = 50,
) -> dict:
    """List jobs in the dead-letter queue (FAILED or TIMEOUT status)."""
    stmt = (
        select(Job)
        .where(Job.status.in_(DLQ_STATUSES))
        .order_by(Job.updated_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return {
        "count": len(jobs),
        "jobs": [
            {
                "job_id": j.id,
                "status": j.status,
                "error_message": j.error_message,
                "retry_count": j.retry_count,
                "schema_name": j.schema_name,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            }
            for j in jobs
        ],
    }


@router.post("/dlq/{job_id}/replay")
async def replay_dlq_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key_id: str = Depends(check_rate_limit),
) -> dict:
    """Replay a failed/timeout job by resetting its status and re-running."""
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)

    if job.status not in DLQ_STATUSES:
        return {
            "job_id": job_id,
            "replayed": False,
            "message": f"Job not in DLQ (status={job.status}). Only FAILED/TIMEOUT jobs can be replayed.",
        }

    # Reset job for re-processing
    old_status = job.status
    job.status = JobStatus.PENDING.value
    job.error_message = f"Replayed from {old_status} at {job.updated_at}"
    job.retry_count = 0  # Reset retry count for fresh attempt

    # Use outbox pattern for Redis queue mode
    if settings.use_redis_queue:
        outbox_event = OutboxEvent(
            event_type=OutboxEventType.REPLAY_JOB.value,
            payload=json.dumps({"job_id": job.id, "replayed_from": old_status}),
            job_id=job.id,
        )
        db.add(outbox_event)
    
    await db.commit()

    # For non-Redis mode, still use background tasks
    if not settings.use_redis_queue:
        background_tasks.add_task(_run_pipeline_bg, job.id)

    return {
        "job_id": job_id,
        "replayed": True,
        "previous_status": old_status,
        "message": "Job replayed and queued for processing.",
    }


@router.post("/dlq/replay-all")
async def replay_all_dlq_jobs(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key_id: str = Depends(check_rate_limit),
    limit: int = 100,
) -> dict:
    """Replay all jobs in the DLQ (up to limit)."""
    stmt = (
        select(Job)
        .where(Job.status.in_(DLQ_STATUSES))
        .order_by(Job.created_at)
        .limit(limit)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    count = 0
    for job in jobs:
        old_status = job.status
        job.status = JobStatus.PENDING.value
        job.error_message = f"Bulk replayed from {old_status}"
        job.retry_count = 0

        if settings.use_redis_queue:
            outbox_event = OutboxEvent(
                event_type=OutboxEventType.REPLAY_JOB.value,
                payload=json.dumps({"job_id": job.id, "replayed_from": old_status}),
                job_id=job.id,
            )
            db.add(outbox_event)
        else:
            background_tasks.add_task(_run_pipeline_bg, job.id)
        count += 1

    await db.commit()

    return {
        "replayed": count,
        "message": f"Replayed {count} job(s) from DLQ",
    }


# ═══════════════════════════════════════════════════════════════════════
# GET /metrics  (observability)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/metrics")
async def get_metrics() -> dict:
    """Return in-process metrics summary + distributed controls status."""
    summary = metrics.summary()
    summary["retry_budget"] = await get_retry_budget_status_distributed(
        budget_per_hour=settings.retry_budget_per_hour,
        window_seconds=3600,
    )
    summary["degradation"] = await get_degradation_status()
    return summary


# ═══════════════════════════════════════════════════════════════════════
# GET /queue-status  (Redis queue observability)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/queue-status")
async def get_queue_status() -> dict:
    """Return Redis queue depth, processing count, and completed jobs."""
    if not settings.use_redis_queue:
        return {"enabled": False, "message": "Redis queue is not enabled (USE_REDIS_QUEUE=false)"}
    from app.worker.queue import get_queue_stats
    stats = await get_queue_stats()
    return {
        "enabled": True,
        **stats,
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/reap-stale-jobs  (manual trigger for reaper)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/admin/reap-stale-jobs")
async def trigger_reaper(
    api_key_id: str = Depends(check_rate_limit),
) -> dict:
    """Manually trigger the stale job reaper."""
    if not settings.use_redis_queue:
        return {"enabled": False, "message": "Redis queue is not enabled"}
    from app.worker.queue import reap_stale_jobs
    recovered = await reap_stale_jobs()
    return {
        "recovered": recovered,
        "message": f"Recovered {recovered} stale job(s) from processing queue",
    }


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/outbox-status  (outbox dispatcher observability)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/admin/outbox-status")
async def get_outbox_status(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return status of the transactional outbox."""
    from sqlalchemy import func
    
    # Count pending events
    pending_stmt = select(func.count()).select_from(OutboxEvent).where(OutboxEvent.delivered == False)
    pending_result = await db.execute(pending_stmt)
    pending_count = pending_result.scalar() or 0
    
    # Count delivered events
    delivered_stmt = select(func.count()).select_from(OutboxEvent).where(OutboxEvent.delivered == True)
    delivered_result = await db.execute(delivered_stmt)
    delivered_count = delivered_result.scalar() or 0
    
    # Count failed events (max attempts reached)
    failed_stmt = (
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.delivered == False)
        .where(OutboxEvent.delivery_attempts >= 5)
    )
    failed_result = await db.execute(failed_stmt)
    failed_count = failed_result.scalar() or 0
    
    return {
        "pending": pending_count,
        "delivered": delivered_count,
        "failed": failed_count,
        "total": pending_count + delivered_count,
    }
