"""Recover jobs stuck in the processing queue.

Run with: python -m app.worker.reaper
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import get_settings
from app.utils.logging import setup_logging
from app.worker.queue import reap_stale_jobs, STALE_JOB_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)
settings = get_settings()

_shutdown = asyncio.Event()

# Poll interval
REAPER_INTERVAL_SECONDS = 30


def _handle_signal(*_: object) -> None:
    logger.info("Shutdown signal received – stopping reaper...")
    _shutdown.set()


async def reaper_loop() -> None:
    """Periodically check for and recover stale jobs."""
    logger.info(
        "Reaper started | stale_timeout=%ds | interval=%ds",
        STALE_JOB_TIMEOUT_SECONDS, REAPER_INTERVAL_SECONDS
    )
    
    while not _shutdown.is_set():
        try:
            recovered = await reap_stale_jobs()
            if recovered > 0:
                logger.info("Recovered %d stale job(s)", recovered)
        except Exception:
            logger.exception("Error in reaper loop")
        
        # Wait before next check (interruptible)
        try:
            await asyncio.wait_for(
                _shutdown.wait(),
                timeout=REAPER_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass
    
    logger.info("Reaper stopped")


async def main() -> None:
    """Entry point for the reaper."""
    setup_logging()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)
    
    logger.info("Starting stale job reaper | redis=%s", settings.redis_url)
    await reaper_loop()


if __name__ == "__main__":
    asyncio.run(main())
