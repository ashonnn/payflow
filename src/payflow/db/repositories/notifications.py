from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Notification
from payflow.domain.enums import EventType


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, user_id: UUID, event_id: int, event_type: EventType, message: str
    ) -> bool:
        """Store a notification once per event and user; False if it already exists."""
        result = await self._session.scalars(
            insert(Notification)
            .values(
                user_id=user_id,
                event_id=event_id,
                event_type=event_type,
                message=message,
            )
            .on_conflict_do_nothing(
                index_elements=[Notification.event_id, Notification.user_id]
            )
            .returning(Notification.id)
        )
        return result.one_or_none() is not None

    async def list_for_user(
        self, user_id: UUID, *, before_id: int | None, limit: int
    ) -> Sequence[Notification]:
        statement = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            statement = statement.where(Notification.id < before_id)
        result = await self._session.scalars(statement)
        return result.all()
