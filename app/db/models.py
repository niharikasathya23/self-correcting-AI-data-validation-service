"""SQLAlchemy ORM models for the data-validation agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

import enum


# ═══════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════

class JobStatus(str, enum.Enum):
    """Lifecycle states of a processing job."""
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    CORRECTING = "CORRECTING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class ValidationStatus(str, enum.Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    PARTIAL = "PARTIAL"


# ═══════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════

class Job(Base):
    """Root record for each processing request."""
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    schema_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    input_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="SHA-256 of (schema_name, raw_text) for deduplication",
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True,
        comment="Client-provided key to prevent duplicate submissions",
    )
    api_key_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="Hashed API key ID for per-tenant tracking",
    )
    status: Mapped[str] = mapped_column(
        String(20), default=JobStatus.PENDING.value, nullable=False
    )
    validation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    structured_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Attempt(Base):
    """One LLM extraction / correction attempt within a job."""
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_sent: Mapped[str] = mapped_column(Text, nullable=False)
    llm_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_errors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(default=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class OutboxEventType(str, enum.Enum):
    """Types of events that can be published via the outbox."""
    ENQUEUE_JOB = "ENQUEUE_JOB"
    REPLAY_JOB = "REPLAY_JOB"


class OutboxEvent(Base):
    """Transactional outbox for reliable event publishing.
    
    Events are written in the same transaction as the entity change,
    then a separate dispatcher reads and publishes them to Redis.
    This ensures atomicity between DB state and queue state.
    """
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON payload
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    delivered: Mapped[bool] = mapped_column(default=False, index=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
