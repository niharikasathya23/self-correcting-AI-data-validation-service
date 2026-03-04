"""Distributed runtime controls backed by Redis with in-memory fallback.

Used for:
- API rate limiting (sliding window per API key)
- Per-API-key retry budget (tenant isolation)
- Global retry budget (sliding window, per hour)
- Degradation detection (retry rate spike detection + auto-fallback)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

from app.core.config import get_settings
from app.worker.queue import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()

RATE_LIMIT_PREFIX = "dvagent:ratelimit"
RETRY_BUDGET_KEY = "dvagent:retry_budget"
RETRY_BUDGET_PER_KEY_PREFIX = "dvagent:retry_budget_key"
DEGRADATION_JOBS_KEY = "dvagent:degradation:jobs"
DEGRADATION_RETRIES_KEY = "dvagent:degradation:retries"

_local_rate_requests: dict[str, list[float]] = defaultdict(list)
_local_retry_timestamps: list[float] = []
_local_per_key_retry_timestamps: dict[str, list[float]] = defaultdict(list)
_local_degradation_jobs: list[float] = []  # timestamps of jobs started
_local_degradation_retries: list[float] = []  # timestamps of retries


def _local_cleanup_rate(key: str, now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    _local_rate_requests[key] = [t for t in _local_rate_requests[key] if t > cutoff]


def _local_cleanup_retry(now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    global _local_retry_timestamps
    _local_retry_timestamps = [t for t in _local_retry_timestamps if t > cutoff]


def _local_cleanup_per_key_retry(key: str, now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    _local_per_key_retry_timestamps[key] = [
        t for t in _local_per_key_retry_timestamps[key] if t > cutoff
    ]


def _local_cleanup_degradation(now: float, window_seconds: int) -> None:
    global _local_degradation_jobs, _local_degradation_retries
    cutoff = now - window_seconds
    _local_degradation_jobs = [t for t in _local_degradation_jobs if t > cutoff]
    _local_degradation_retries = [t for t in _local_degradation_retries if t > cutoff]


async def check_rate_limit_distributed(
    key: str,
    rpm: int,
    window_seconds: int = 60,
) -> tuple[bool, int, int]:
    """Check request allowance using Redis sliding window.

    Returns: (allowed, remaining, reset_seconds)
    Falls back to in-memory state if Redis is unavailable.
    """
    now = time.time()
    redis_key = f"{RATE_LIMIT_PREFIX}:{key}"

    try:
        redis_client = await get_redis()
        try:
            cutoff = now - window_seconds
            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(redis_key, "-inf", cutoff)
            pipe.zcard(redis_key)
            pipe.zrange(redis_key, 0, 0, withscores=True)
            await pipe.execute()

            current_count = await redis_client.zcard(redis_key)
            oldest_with_score = await redis_client.zrange(redis_key, 0, 0, withscores=True)

            if current_count >= rpm:
                if oldest_with_score:
                    oldest_ts = oldest_with_score[0][1]
                    reset_seconds = max(1, int(window_seconds - (now - oldest_ts)))
                else:
                    reset_seconds = window_seconds
                return False, 0, reset_seconds

            member = f"{now}:{current_count}"
            await redis_client.zadd(redis_key, {member: now})
            await redis_client.expire(redis_key, window_seconds + 5)

            remaining = max(0, rpm - (current_count + 1))
            if oldest_with_score:
                oldest_ts = oldest_with_score[0][1]
                reset_seconds = max(1, int(window_seconds - (now - oldest_ts)))
            else:
                reset_seconds = window_seconds
            return True, remaining, reset_seconds
        finally:
            await redis_client.aclose()
    except Exception as exc:
        logger.warning("Redis rate-limit unavailable, using local fallback: %s", exc)

    _local_cleanup_rate(key, now, window_seconds)
    current_count = len(_local_rate_requests[key])
    if current_count >= rpm:
        oldest_ts = _local_rate_requests[key][0] if _local_rate_requests[key] else now
        reset_seconds = max(1, int(window_seconds - (now - oldest_ts)))
        return False, 0, reset_seconds

    _local_rate_requests[key].append(now)
    remaining = max(0, rpm - len(_local_rate_requests[key]))
    oldest_ts = _local_rate_requests[key][0] if _local_rate_requests[key] else now
    reset_seconds = max(1, int(window_seconds - (now - oldest_ts)))
    return True, remaining, reset_seconds


async def consume_retry_budget(
    budget_per_hour: int,
    window_seconds: int = 3600,
    api_key_id: Optional[str] = None,
    per_key_budget: Optional[int] = None,
) -> tuple[bool, int, str]:
    """Consume one retry budget token.

    Checks both global budget AND per-API-key budget (if api_key_id provided).
    Returns: (allowed, remaining_global, rejection_reason)
    Falls back to in-memory state if Redis is unavailable.
    """
    now = time.time()
    rejection_reason = ""
    
    # First check per-API-key budget if provided
    if api_key_id and per_key_budget is not None:
        key_allowed, key_remaining = await _consume_per_key_budget(
            api_key_id, per_key_budget, window_seconds
        )
        if not key_allowed:
            logger.warning("Per-key retry budget exhausted for %s", api_key_id[:8])
            return False, 0, "PER_KEY_BUDGET_EXHAUSTED"
    
    # Then check global budget
    try:
        redis_client = await get_redis()
        try:
            cutoff = now - window_seconds
            await redis_client.zremrangebyscore(RETRY_BUDGET_KEY, "-inf", cutoff)
            used = await redis_client.zcard(RETRY_BUDGET_KEY)
            if used >= budget_per_hour:
                return False, 0, "GLOBAL_BUDGET_EXHAUSTED"

            member = f"{now}:{used}"
            await redis_client.zadd(RETRY_BUDGET_KEY, {member: now})
            await redis_client.expire(RETRY_BUDGET_KEY, window_seconds + 60)
            remaining = max(0, budget_per_hour - (used + 1))
            return True, remaining, ""
        finally:
            await redis_client.aclose()
    except Exception as exc:
        logger.warning("Redis retry-budget unavailable, using local fallback: %s", exc)

    _local_cleanup_retry(now, window_seconds)
    used = len(_local_retry_timestamps)
    if used >= budget_per_hour:
        return False, 0, "GLOBAL_BUDGET_EXHAUSTED"
    _local_retry_timestamps.append(now)
    return True, max(0, budget_per_hour - len(_local_retry_timestamps)), ""


async def _consume_per_key_budget(
    api_key_id: str,
    budget_per_hour: int,
    window_seconds: int = 3600,
) -> tuple[bool, int]:
    """Consume one retry token from a per-API-key budget."""
    now = time.time()
    redis_key = f"{RETRY_BUDGET_PER_KEY_PREFIX}:{api_key_id}"
    
    try:
        redis_client = await get_redis()
        try:
            cutoff = now - window_seconds
            await redis_client.zremrangebyscore(redis_key, "-inf", cutoff)
            used = await redis_client.zcard(redis_key)
            if used >= budget_per_hour:
                return False, 0

            member = f"{now}:{used}"
            await redis_client.zadd(redis_key, {member: now})
            await redis_client.expire(redis_key, window_seconds + 60)
            return True, max(0, budget_per_hour - (used + 1))
        finally:
            await redis_client.aclose()
    except Exception:
        # Local fallback for per-key budget
        _local_cleanup_per_key_retry(api_key_id, now, window_seconds)
        used = len(_local_per_key_retry_timestamps[api_key_id])
        if used >= budget_per_hour:
            return False, 0
        _local_per_key_retry_timestamps[api_key_id].append(now)
        return True, max(0, budget_per_hour - len(_local_per_key_retry_timestamps[api_key_id]))


async def get_retry_budget_status_distributed(
    budget_per_hour: int,
    window_seconds: int = 3600,
) -> dict:
    """Get retry budget status from Redis (or local fallback)."""
    now = time.time()
    try:
        redis_client = await get_redis()
        try:
            cutoff = now - window_seconds
            await redis_client.zremrangebyscore(RETRY_BUDGET_KEY, "-inf", cutoff)
            used = await redis_client.zcard(RETRY_BUDGET_KEY)
        finally:
            await redis_client.aclose()
    except Exception:
        _local_cleanup_retry(now, window_seconds)
        used = len(_local_retry_timestamps)

    remaining = max(0, budget_per_hour - used)
    return {
        "budget_per_hour": budget_per_hour,
        "used_this_hour": used,
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }


# ═══════════════════════════════════════════════════════════════════════
# Degradation Detection
# ═══════════════════════════════════════════════════════════════════════

async def record_job_start() -> None:
    """Record that a job has started (for retry rate calculation)."""
    now = time.time()
    try:
        redis_client = await get_redis()
        try:
            member = f"{now}"
            await redis_client.zadd(DEGRADATION_JOBS_KEY, {member: now})
            await redis_client.expire(DEGRADATION_JOBS_KEY, settings.degradation_window_seconds + 60)
        finally:
            await redis_client.aclose()
    except Exception:
        _local_degradation_jobs.append(now)


async def record_retry_attempt() -> None:
    """Record that a retry was attempted (for retry rate calculation)."""
    now = time.time()
    try:
        redis_client = await get_redis()
        try:
            member = f"{now}"
            await redis_client.zadd(DEGRADATION_RETRIES_KEY, {member: now})
            await redis_client.expire(DEGRADATION_RETRIES_KEY, settings.degradation_window_seconds + 60)
        finally:
            await redis_client.aclose()
    except Exception:
        _local_degradation_retries.append(now)


async def get_degradation_status() -> dict:
    """Check if system is in degraded state based on retry rate.
    
    Returns dict with:
    - is_degraded: bool - True if retry rate exceeds threshold
    - retry_rate: float - current retry rate (retries / jobs)
    - jobs_in_window: int
    - retries_in_window: int
    - threshold: float
    - recommend_fallback: bool
    """
    now = time.time()
    cutoff = now - settings.degradation_window_seconds
    jobs_count = 0
    retries_count = 0
    
    try:
        redis_client = await get_redis()
        try:
            await redis_client.zremrangebyscore(DEGRADATION_JOBS_KEY, "-inf", cutoff)
            await redis_client.zremrangebyscore(DEGRADATION_RETRIES_KEY, "-inf", cutoff)
            jobs_count = await redis_client.zcard(DEGRADATION_JOBS_KEY)
            retries_count = await redis_client.zcard(DEGRADATION_RETRIES_KEY)
        finally:
            await redis_client.aclose()
    except Exception:
        _local_cleanup_degradation(now, settings.degradation_window_seconds)
        jobs_count = len(_local_degradation_jobs)
        retries_count = len(_local_degradation_retries)
    
    # Calculate retry rate (avoid division by zero)
    retry_rate = retries_count / max(jobs_count, 1)
    is_degraded = retry_rate > settings.degradation_retry_rate_threshold
    
    return {
        "is_degraded": is_degraded,
        "retry_rate": round(retry_rate, 3),
        "jobs_in_window": jobs_count,
        "retries_in_window": retries_count,
        "window_seconds": settings.degradation_window_seconds,
        "threshold": settings.degradation_retry_rate_threshold,
        "recommend_fallback": is_degraded and settings.auto_fallback_on_degradation,
    }


async def should_use_fallback_model() -> bool:
    """Check if we should use fallback model due to degradation."""
    if not settings.auto_fallback_on_degradation:
        return False
    status = await get_degradation_status()
    if status["recommend_fallback"]:
        logger.warning(
            "Degradation detected (retry_rate=%.2f > threshold=%.2f), using fallback model",
            status["retry_rate"], status["threshold"]
        )
    return status["recommend_fallback"]
