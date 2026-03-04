"""Structured error codes and exception classes for consistent API responses."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException, status


class ErrorCode(str, Enum):
    """Machine-readable error codes returned in API responses."""

    # ── Authentication (401) ─────────────────────────────────────────────
    AUTH_MISSING_KEY = "AUTH_MISSING_KEY"
    AUTH_INVALID_KEY = "AUTH_INVALID_KEY"

    # ── Rate Limiting (429) ──────────────────────────────────────────────
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # ── Validation (400) ─────────────────────────────────────────────────
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_SCHEMA_NAME = "INVALID_SCHEMA_NAME"
    INVALID_REQUEST_BODY = "INVALID_REQUEST_BODY"

    # ── Job Errors (4xx/5xx) ─────────────────────────────────────────────
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_ALREADY_EXISTS = "JOB_ALREADY_EXISTS"
    JOB_TIMEOUT = "JOB_TIMEOUT"
    JOB_CANCELLED = "JOB_CANCELLED"

    # ── LLM Provider (502/503) ───────────────────────────────────────────
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_QUOTA_EXCEEDED = "LLM_QUOTA_EXCEEDED"
    LLM_TIMEOUT = "LLM_TIMEOUT"

    # ── Queue / Worker (503) ─────────────────────────────────────────────
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"

    # ── Database (500) ───────────────────────────────────────────────────
    DATABASE_ERROR = "DATABASE_ERROR"

    # ── Internal (500) ───────────────────────────────────────────────────
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PIPELINE_ERROR = "PIPELINE_ERROR"


class APIError(HTTPException):
    """Base exception for all API errors with structured response."""

    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        detail = {
            "error_code": error_code.value,
            "message": message,
        }
        if details:
            detail["details"] = details
        super().__init__(status_code=status_code, detail=detail, headers=headers)


# ═══════════════════════════════════════════════════════════════════════
# Specific error classes for common cases
# ═══════════════════════════════════════════════════════════════════════

class AuthenticationError(APIError):
    """401 Unauthorized errors."""

    def __init__(self, error_code: ErrorCode, message: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code=error_code,
            message=message,
        )


class RateLimitError(APIError):
    """429 Too Many Requests errors."""

    def __init__(self, retry_after: int):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=f"Rate limit exceeded. Try again in {retry_after}s.",
            details={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


class ValidationError(APIError):
    """400 Bad Request for validation failures."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
        )


class NotFoundError(APIError):
    """404 Not Found errors."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.JOB_NOT_FOUND,
            message=f"{resource} '{identifier}' not found",
        )


class LLMProviderError(APIError):
    """502/503 for LLM provider failures."""

    def __init__(self, error_code: ErrorCode, message: str, provider: str):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_code=error_code,
            message=message,
            details={"provider": provider},
        )


class JobTimeoutError(APIError):
    """408 Request Timeout for jobs that exceed time limit."""

    def __init__(self, job_id: str, timeout_seconds: int):
        super().__init__(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            error_code=ErrorCode.JOB_TIMEOUT,
            message=f"Job '{job_id}' exceeded timeout of {timeout_seconds}s",
            details={"job_id": job_id, "timeout_seconds": timeout_seconds},
        )


class InternalError(APIError):
    """500 Internal Server Error."""

    def __init__(self, message: str = "An unexpected error occurred"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ErrorCode.INTERNAL_ERROR,
            message=message,
        )


# ═══════════════════════════════════════════════════════════════════════
# Helper for consistent error responses
# ═══════════════════════════════════════════════════════════════════════

def error_response(
    error_code: ErrorCode,
    message: str,
    details: Optional[dict] = None,
) -> dict:
    """Build a structured error response dict (for pipeline status updates)."""
    resp = {"error_code": error_code.value, "message": message}
    if details:
        resp["details"] = details
    return resp
