import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.core.metrics import OUTBOX_DELIVERIES
from payflow.db.models import OutboxEvent
from payflow.db.repositories.outbox import OutboxRepository
from payflow.workers.scheduler import sleep_until_stopped

logger = structlog.get_logger(__name__)

type EventHandler = Callable[[AsyncSession, OutboxEvent], Awaitable[None]]


class OutboxRelay:
    """Hands committed outbox events to a handler, at least once, with backoff."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handler: EventHandler,
        *,
        batch_size: int,
        max_attempts: int,
        retry_base: timedelta,
        poll_interval: timedelta,
    ) -> None:
        self._session_factory = session_factory
        self._handler = handler
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._retry_base = retry_base
        self._poll_interval = poll_interval

    async def run(self, stop: asyncio.Event) -> None:
        logger.info("outbox.relay_started")
        while not stop.is_set():
            try:
                handled = await self.run_once()
            except Exception:
                logger.exception("outbox.batch_failed")
                handled = 0
            if handled < self._batch_size:
                await sleep_until_stopped(stop, self._poll_interval)
        logger.info("outbox.relay_stopped")

    async def run_once(self) -> int:
        """Process one batch; returns how many events were attempted."""
        async with self._session_factory() as session:
            outbox = OutboxRepository(session)
            events = await outbox.claim_due(self._batch_size)
            for event in events:
                await self._deliver(session, outbox, event)
            await session.commit()
        return len(events)

    async def _deliver(
        self, session: AsyncSession, outbox: OutboxRepository, event: OutboxEvent
    ) -> None:
        event_id, event_type, attempts = event.id, event.event_type, event.attempts
        try:
            # a failing handler only rolls back its own savepoint, not the batch
            async with session.begin_nested():
                await self._handler(session, event)
        except Exception as exc:
            retry_in = self._backoff(attempts)
            await outbox.mark_failed_attempt(event_id, repr(exc)[:1000], retry_in)
            outcome = "retry" if retry_in else "dead_letter"
            OUTBOX_DELIVERIES.labels(event_type, outcome).inc()
            logger.log(
                logging.WARNING if retry_in else logging.ERROR,
                "outbox.delivery_failed",
                event_id=event_id,
                event_type=event_type,
                attempt=attempts + 1,
                retry_in_seconds=retry_in.total_seconds() if retry_in else None,
                exc_info=True,
            )
        else:
            await outbox.mark_processed(event_id)
            OUTBOX_DELIVERIES.labels(event_type, "delivered").inc()
            logger.info("outbox.delivered", event_id=event_id, event_type=event_type)

    def _backoff(self, attempts_so_far: int) -> timedelta | None:
        if attempts_so_far + 1 >= self._max_attempts:
            return None
        return self._retry_base * (1 << attempts_so_far)
