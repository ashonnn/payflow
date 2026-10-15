from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import OutboxEvent, Transaction
from payflow.domain.enums import EventType
from payflow.domain.events import transaction_payload


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def publish(self, event_type: EventType, transaction: Transaction) -> None:
        """Queue an event in the caller's transaction; the worker delivers it later."""
        self._session.add(
            OutboxEvent(event_type=event_type, payload=transaction_payload(transaction))
        )
