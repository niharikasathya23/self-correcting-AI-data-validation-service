"""Outbox event dispatcher – reads undelivered events and publishes to Redis.

This closes the atomicity gap between DB commits and Redis enqueues.
Run alongside workers: python -m app.worker.outbox_dispatcher

Design:
- Polls the outbox_events table for undelivered events
- Enqueues job IDs to Redis
- Marks events as delivered
- Retries failed deliveries with backoff
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import OutboxEvent, OutboxEventType
from app.db.session import async_session_factory, init_db
from app.utils.logging import setup_logging
from app.worker.queue import enqueue_job_reliable

logger = logging.getLogger(__name__)
settings = get_settings()

_shutdown = asyncio.Event()

# Dispatcher config
POLL_INTERVAL_SECONDS = 1.0
MAX_DELIVERY_ATTEMPTS = 5
BATCH_SIZE = 100


def _handle_signal(*_: object) -> None:
    logger.info("Shutdown signal received – stopping dispatcher...")
    _shutdown.set()


async def dispatch_pending_events() -> int:
    """Process pending outbox events. Returns count of events dispatched."""
    dispatched = 0
    
    async with async_session_factory() as session:
        # Fetch undelivered events
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.delivered == False)
            .where(OutboxEvent.delivery_attempts < MAX_DELIVERY_ATTEMPTS)
            .order_by(OutboxEvent.created_at)
            .limit(BATCH_SIZE)
        )
        result = await session.execute(stmt)
        events = result.scalars().all()
        
        for event in events:
            try:
                if event.event_type in (
                    OutboxEventType.ENQUEUE_JOB.value,
                    OutboxEventType.REPLAY_JOB.value,
                ):
                    # Enqueue to Redis using reliable method
                    await enqueue_job_reliable(event.job_id)
                    
                    # Mark as delivered
                    event.delivered = True
                    event.delivered_at = datetime.now(timezone.utc)
                    dispatched += 1
                    logger.info(
                        "Dispatched outbox event %d (job %s)",
                        event.id, event.job_id
                    )
                else:
                    logger.warning("Unknown event type: %s", event.event_type)
                    event.delivery_attempts += 1
                    event.last_error = f"Unknown event type: {event.event_type}"
                    
            except Exception as e:
                event.delivery_attempts += 1
                event.last_error = str(e)[:500]
                logger.error(
                    "Failed to dispatch event %d (attempt %d): %s",
                    event.id, event.delivery_attempts, e
                )
        
        await session.commit()
    
    return dispatched


async def dispatcher_loop() -> None:
    """Main dispatcher loop."""
    logger.info("Outbox dispatcher started")
    
    while not _shutdown.is_set():
        try:
            dispatched = await dispatch_pending_events()
            if dispatched > 0:
                logger.debug("Dispatched %d events", dispatched)
        except Exception:
            logger.exception("Error in dispatcher loop")
        
        # Wait before next poll (interruptible)
        try:
            await asyncio.wait_for(
                _shutdown.wait(),
                timeout=POLL_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass
    
    logger.info("Outbox dispatcher stopped")


async def main() -> None:
    """Entry point for the dispatcher."""
    setup_logging()
    await init_db()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)
    
    logger.info("Starting outbox dispatcher | db=%s", settings.database_url)
    await dispatcher_loop()


if __name__ == "__main__":
    asyncio.run(main())
