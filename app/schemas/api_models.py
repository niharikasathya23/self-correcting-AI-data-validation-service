"""API request / response models (NOT the data-validation schemas)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ── Requests ─────────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    """POST /process body."""
    raw_text: str = Field(..., min_length=1, description="Unstructured input text")
    schema_name: Optional[str] = Field(
        None,
        description="Target schema name (default: 'invoice'). Options: invoice, survey",
    )


# ── Responses ────────────────────────────────────────────────────────

class AttemptDetail(BaseModel):
    attempt_number: int
    llm_response: Optional[str] = None
    parsed_json: Optional[dict[str, Any]] = None
    validation_errors: Optional[str] = None
    is_valid: bool = False
    tokens_used: int = 0
    latency_ms: float = 0.0
    created_at: Optional[datetime] = None


class ProcessResponse(BaseModel):
    """Returned by POST /process."""
    job_id: str
    status: str
    message: str = "Job enqueued for processing."


class ResultResponse(BaseModel):
    """Returned by GET /result/{job_id}."""
    job_id: str
    status: str
    validation_status: Optional[str] = None
    retry_count: int = 0
    structured_output: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    correction_log: List[AttemptDetail] = []
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Backoff hints for polling clients
    retry_after_seconds: Optional[int] = None
    is_terminal: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
