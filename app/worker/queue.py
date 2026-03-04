"""Redis job queue – reliable queue with LMOVE pattern.

Jobs are pushed onto a pending list. Workers atomically move jobs
to a processing list (LMOVE), process them, then acknowledge.
A reaper recovers stale jobs from the processing list.

Queue design:
  - QUEUE_KEY      (list) : pending job IDs
  - PROCESSING_KEY (list) : job IDs currently being processed (with timestamps)
  - ACTIVE_KEY     (set)  : job IDs currently active (for quick lookup)
  - RESULT_KEY     (hash) : job_id → "done" (dedup / idempotency guard)

Reliability:
  - LMOVE atomically moves from pending → processing
  - If worker crashes, job stays in processing list
  - Reaper moves stale jobs back to pending
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_KEY = "dvagent:jobs:pending"
PROCESSING_KEY = "dvagent:jobs:processing"
ACTIVE_KEY = "dvagent:jobs:active"
RESULT_KEY = "dvagent:jobs:completed"
JOB_START_TIME_KEY = "dvagent:jobs:start_times"  # Hash: job_id → start timestamp

# Config for reaper
STALE_JOB_TIMEOUT_SECONDS = 300  # 5 minutes


async def get_redis() -> aioredis.Redis:
    """Create a Redis client from the configured URL."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def enqueue_job(job_id: str) -> None:
    """Push a job ID onto the pending queue (legacy method)."""
    r = await get_redis()
    try:
        await r.rpush(QUEUE_KEY, job_id)
        logger.info("Enqueued job %s", job_id)
    finally:
        await r.aclose()


async def enqueue_job_reliable(job_id: str) -> None:
    """Push a job ID onto the pending queue (called from outbox dispatcher)."""
    r = await get_redis()
    try:
        # Check if already in queue or processing
        in_active = await r.sismember(ACTIVE_KEY, job_id)
        if in_active:
            logger.debug("Job %s already active, skipping enqueue", job_id)
            return
        
        # Check if already completed
        completed = await r.hget(RESULT_KEY, job_id)
        if completed:
            logger.debug("Job %s already completed, skipping enqueue", job_id)
            return
        
        await r.rpush(QUEUE_KEY, job_id)
        logger.info("Reliably enqueued job %s", job_id)
    finally:
        await r.aclose()


async def dequeue_job(timeout: int = 0) -> Optional[str]:
    """Atomically move job from pending to processing. Returns job_id or None.
    
    Uses BLMOVE (Redis 6.2+) or falls back to BRPOPLPUSH pattern.
    """
    r = await get_redis()
    try:
        # Try BLMOVE first (Redis 6.2+), fall back to BRPOPLPUSH
        try:
            # BLMOVE source destination LEFT|RIGHT LEFT|RIGHT timeout
            job_id = await r.execute_command(
                "BLMOVE", QUEUE_KEY, PROCESSING_KEY, "LEFT", "RIGHT", timeout
            )
        except aioredis.ResponseError:
            # Fall back to BRPOPLPUSH for older Redis
            job_id = await r.brpoplpush(QUEUE_KEY, PROCESSING_KEY, timeout=timeout)
        
        if job_id:
            # Track start time for reaper
            await r.hset(JOB_START_TIME_KEY, job_id, str(time.time()))
            await r.sadd(ACTIVE_KEY, job_id)
            return job_id
        return None
    finally:
        await r.aclose()


async def acknowledge_job(job_id: str, success: bool = True) -> None:
    """Remove job from processing list and update state.
    
    Called after job completes (success or failure).
    """
    r = await get_redis()
    try:
        # Remove from processing list
        await r.lrem(PROCESSING_KEY, 1, job_id)
        # Remove from active set
        await r.srem(ACTIVE_KEY, job_id)
        # Remove start time
        await r.hdel(JOB_START_TIME_KEY, job_id)
        
        if success:
            await r.hset(RESULT_KEY, job_id, "done")
            logger.debug("Acknowledged job %s as completed", job_id)
        else:
            logger.debug("Acknowledged job %s as failed", job_id)
    finally:
        await r.aclose()


async def mark_completed(job_id: str) -> None:
    """Move job from processing to completed (calls acknowledge)."""
    await acknowledge_job(job_id, success=True)


async def mark_failed(job_id: str) -> None:
    """Remove job from processing (failed, stays out of completed)."""
    await acknowledge_job(job_id, success=False)


async def reap_stale_jobs(timeout_seconds: int = STALE_JOB_TIMEOUT_SECONDS) -> int:
    """Move stale jobs from processing back to pending.
    
    Returns the number of jobs recovered.
    """
    r = await get_redis()
    recovered = 0
    try:
        now = time.time()
        
        # Get all jobs in processing list
        processing_jobs = await r.lrange(PROCESSING_KEY, 0, -1)
        
        for job_id in processing_jobs:
            start_time_str = await r.hget(JOB_START_TIME_KEY, job_id)
            if not start_time_str:
                # No start time recorded - might be from before this feature
                # Give it benefit of doubt, record now
                await r.hset(JOB_START_TIME_KEY, job_id, str(now))
                continue
            
            start_time = float(start_time_str)
            elapsed = now - start_time
            
            if elapsed > timeout_seconds:
                # Job is stale - move back to pending
                await r.lrem(PROCESSING_KEY, 1, job_id)
                await r.srem(ACTIVE_KEY, job_id)
                await r.hdel(JOB_START_TIME_KEY, job_id)
                await r.lpush(QUEUE_KEY, job_id)  # Push to front for priority
                
                recovered += 1
                logger.warning(
                    "Recovered stale job %s (was processing for %.0fs)",
                    job_id, elapsed
                )
        
        return recovered
    finally:
        await r.aclose()


async def queue_length() -> int:
    """Number of jobs waiting in the pending queue."""
    r = await get_redis()
    try:
        return await r.llen(QUEUE_KEY)
    finally:
        await r.aclose()


async def processing_count() -> int:
    """Number of jobs currently in processing list."""
    r = await get_redis()
    try:
        return await r.llen(PROCESSING_KEY)
    finally:
        await r.aclose()


async def active_count() -> int:
    """Number of jobs currently being processed by workers."""
    r = await get_redis()
    try:
        return await r.scard(ACTIVE_KEY)
    finally:
        await r.aclose()


async def get_queue_stats() -> dict:
    """Get comprehensive queue statistics."""
    r = await get_redis()
    try:
        pending = await r.llen(QUEUE_KEY)
        processing = await r.llen(PROCESSING_KEY)
        active = await r.scard(ACTIVE_KEY)
        completed = await r.hlen(RESULT_KEY)
        
        return {
            "pending": pending,
            "processing": processing,
            "active": active,
            "completed": completed,
        }
    finally:
        await r.aclose()
