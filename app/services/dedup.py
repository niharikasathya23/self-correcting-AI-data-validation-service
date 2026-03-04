"""Input deduplication using SHA-256 over schema and raw text.

Looks up completed jobs by hash, using Redis when enabled and
falling back to the database.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Job, JobStatus

logger = logging.getLogger(__name__)
settings = get_settings()

REDIS_DEDUP_PREFIX = "dvagent:dedup:"
REDIS_DEDUP_TTL = 3600 * 24  # 24 hours


def compute_input_hash(raw_text: str, schema_name: str | None) -> str:
    """Deterministic SHA-256 of (raw_text, schema_name)."""
    key = f"{schema_name or 'default'}::{raw_text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def find_duplicate_job(
    input_hash: str,
    session: AsyncSession,
) -> Optional[str]:
    """Return the job_id of a previous COMPLETED job with the same hash, or None.

    Checks Redis first (if enabled), then falls back to a DB query.
    """
    # Redis lookup first when enabled
    if settings.use_redis_queue:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                cached = await r.get(f"{REDIS_DEDUP_PREFIX}{input_hash}")
                if cached:
                    logger.info("Dedup cache hit (Redis): hash=%s job=%s", input_hash[:12], cached)
                    return cached
            finally:
                await r.aclose()
        except Exception:
            logger.debug("Redis dedup lookup failed, falling back to DB")

    # Database fallback
    stmt = (
        select(Job.id)
        .where(Job.input_hash == input_hash)
        .where(Job.status == JobStatus.COMPLETED.value)
        .limit(1)
    )
    result = await session.execute(stmt)
    job_id = result.scalar_one_or_none()

    if job_id:
        logger.info("Dedup cache hit (DB): hash=%s job=%s", input_hash[:12], job_id)
    return job_id


async def cache_completed_job(input_hash: str, job_id: str) -> None:
    """Store a completed job's hash→id mapping in Redis for fast lookup."""
    if not settings.use_redis_queue:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.set(
                f"{REDIS_DEDUP_PREFIX}{input_hash}",
                job_id,
                ex=REDIS_DEDUP_TTL,
            )
        finally:
            await r.aclose()
    except Exception:
        logger.debug("Failed to write Redis dedup cache for job %s", job_id)
