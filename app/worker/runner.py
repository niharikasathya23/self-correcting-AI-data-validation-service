"""Redis worker process – run with: python -m app.worker.runner

Continuously pops job IDs from the Redis queue and runs the
LangGraph pipeline.  Designed to be run as N parallel instances
for horizontal scaling.

Usage:
    python -m app.worker.runner                 # single worker
    python -m app.worker.runner --concurrency 4 # 4 concurrent tasks
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

# Ensure project root is on sys.path when run as __main__
sys.path.insert(0, ".")

from app.core.config import get_settings
from app.db.session import async_session_factory, init_db
from app.services.pipeline import run_pipeline
from app.utils.logging import setup_logging
from app.worker.queue import dequeue_job, acknowledge_job

logger = logging.getLogger(__name__)
settings = get_settings()

_shutdown = asyncio.Event()


def _handle_signal(*_: object) -> None:
    logger.info("Shutdown signal received – finishing current jobs...")
    _shutdown.set()


async def _worker_loop(worker_id: int) -> None:
    """Single worker coroutine: pop jobs and run them."""
    logger.info("Worker-%d started", worker_id)

    while not _shutdown.is_set():
        job_id = await dequeue_job(timeout=2)  # 2s blocking pop
        if job_id is None:
            continue

        logger.info("Worker-%d picked up job %s", worker_id, job_id)
        success = False
        try:
            async with async_session_factory() as session:
                await run_pipeline(job_id, session)
            success = True
            logger.info("Worker-%d completed job %s", worker_id, job_id)
        except Exception:
            logger.exception("Worker-%d failed on job %s", worker_id, job_id)
        finally:
            # Always acknowledge to remove from processing queue
            await acknowledge_job(job_id, success=success)

    logger.info("Worker-%d stopped", worker_id)


async def main(concurrency: int = 1) -> None:
    """Start *concurrency* worker loops."""
    setup_logging()
    await init_db()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info(
        "Starting %d worker(s) | redis=%s | db=%s",
        concurrency, settings.redis_url, settings.database_url,
    )

    workers = [asyncio.create_task(_worker_loop(i)) for i in range(concurrency)]
    await asyncio.gather(*workers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redis job-queue worker")
    parser.add_argument(
        "--concurrency", "-c", type=int, default=1,
        help="Number of concurrent worker tasks (default: 1)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.concurrency))
