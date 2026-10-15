from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import IdempotencyKey


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self, user_id: UUID, key: str, fingerprint: str
    ) -> IdempotencyKey | None:
        """Reserve the key, or return the earlier request that already used it.

        A duplicate in flight makes this wait until the first request finishes."""
        claimed = await self._session.scalars(
            insert(IdempotencyKey)
            .values(user_id=user_id, key=key, request_fingerprint=fingerprint)
            .on_conflict_do_nothing(
                index_elements=[IdempotencyKey.user_id, IdempotencyKey.key]
            )
            .returning(IdempotencyKey.key)
        )
        if claimed.one_or_none() is not None:
            return None
        previous = await self._session.scalars(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
            )
        )
        return previous.one()

    async def store_response(
        self, user_id: UUID, key: str, status_code: int, body: dict[str, Any]
    ) -> None:
        await self._session.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
            .values(response_status=status_code, response_body=body)
        )

    async def purge_created_before(self, cutoff: datetime) -> int:
        connection = await self._session.connection()
        result = await connection.execute(
            delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff)
        )
        return result.rowcount
