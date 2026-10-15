from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Notification, OutboxEvent
from payflow.db.repositories.notifications import NotificationRepository
from payflow.db.repositories.users import UserRepository
from payflow.domain.enums import EventType

logger = structlog.get_logger(__name__)


def format_money(amount: str, currency: str) -> str:
    return f"{Decimal(amount):,.2f} {currency}"


def mask_phone(phone: str) -> str:
    return f"{phone[:5]}***{phone[-4:]}"


class NotificationService:
    """Turns ledger events into messages for the people involved."""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._notifications = NotificationRepository(session)

    async def recent(
        self, user_id: UUID, *, before_id: int | None, limit: int
    ) -> Sequence[Notification]:
        return await self._notifications.list_for_user(
            user_id, before_id=before_id, limit=limit
        )

    async def notify(self, event: OutboxEvent) -> None:
        for user_id, message in await self._messages(event.event_type, event.payload):
            if await self._notifications.add(
                user_id, event.id, event.event_type, message
            ):
                # stands in for the push or sms gateway call
                logger.info(
                    "notification.sent",
                    user_id=str(user_id),
                    event_id=event.id,
                    event_type=event.event_type,
                )

    async def _messages(
        self, event_type: EventType, payload: dict[str, Any]
    ) -> list[tuple[UUID, str]]:
        initiator_id = UUID(payload["initiator_id"])
        amount = format_money(payload["amount"], payload["currency"])
        match event_type:
            case EventType.DEPOSIT_COMPLETED:
                return [(initiator_id, f"{amount} was added to your wallet")]
            case EventType.DEPOSIT_FAILED:
                reason = payload["failure_reason"]
                return [(initiator_id, f"Your deposit of {amount} failed: {reason}")]
            case EventType.EXCHANGE_COMPLETED:
                received = format_money(
                    payload["counter_amount"], payload["counter_currency"]
                )
                return [(initiator_id, f"You exchanged {amount} for {received}")]
            case EventType.TRANSFER_HELD:
                return [(initiator_id, f"Your transfer of {amount} is under review")]
            case EventType.TRANSFER_REJECTED:
                return [
                    (
                        initiator_id,
                        f"Your transfer of {amount} was declined and refunded",
                    )
                ]
            case EventType.TRANSFER_COMPLETED:
                recipient_id = UUID(payload["counterparty_id"])
                sender_phone = await self._phone(initiator_id)
                recipient_phone = await self._phone(recipient_id)
                return [
                    (
                        initiator_id,
                        f"You sent {amount} to {mask_phone(recipient_phone)}",
                    ),
                    (
                        recipient_id,
                        f"You received {amount} from {mask_phone(sender_phone)}",
                    ),
                ]

    async def _phone(self, user_id: UUID) -> str:
        user = await self._users.get(user_id)
        if user is None:
            raise LookupError(f"user {user_id} referenced by an event does not exist")
        return user.phone
