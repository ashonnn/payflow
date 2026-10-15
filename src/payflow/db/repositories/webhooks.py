from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import WebhookEvent


class WebhookEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self, event_id: str, event_type: str, payload: dict[str, Any]
    ) -> bool:
        """Store a delivered event; returns False if it was already processed."""
        statement = (
            insert(WebhookEvent)
            .values(id=event_id, event_type=event_type, payload=payload)
            .on_conflict_do_nothing(index_elements=[WebhookEvent.id])
            .returning(WebhookEvent.id)
        )
        result = await self._session.scalars(statement)
        return result.one_or_none() is not None
