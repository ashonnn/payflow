from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import OutboxEvent, Transaction
from payflow.domain.enums import EventType, OutboxStatus
from payflow.domain.events import transaction_payload


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def publish(self, event_type: EventType, transaction: Transaction) -> None:
        """Queue an event in the caller's transaction; the worker delivers it later."""
        self._session.add(
            OutboxEvent(event_type=event_type, payload=transaction_payload(transaction))
        )

    async def claim_due(self, limit: int) -> Sequence[OutboxEvent]:
        """Lock a batch of due events; rows held by another relay are skipped."""
        result = await self._session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.available_at <= func.now(),
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.all()

    async def mark_processed(self, event_id: int) -> None:
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(status=OutboxStatus.PROCESSED, processed_at=func.now())
        )

    async def mark_failed_attempt(
        self, event_id: int, error: str, retry_in: timedelta | None
    ) -> None:
        """Count a failed delivery; without `retry_in` the event is given up on."""
        values = (
            {"available_at": func.now() + retry_in}
            if retry_in is not None
            else {"status": OutboxStatus.FAILED}
        )
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(attempts=OutboxEvent.attempts + 1, last_error=error, **values)
        )
