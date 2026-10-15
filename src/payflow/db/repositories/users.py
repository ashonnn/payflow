from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self._session.scalars(select(User).where(User.phone == phone))
        return result.one_or_none()

    async def create(
        self, *, phone: str, full_name: str, password_hash: str, is_admin: bool = False
    ) -> User | None:
        """Insert a user; returns None when the phone is already taken."""
        statement = (
            insert(User)
            .values(
                phone=phone,
                full_name=full_name,
                password_hash=password_hash,
                is_admin=is_admin,
            )
            .on_conflict_do_nothing(index_elements=[User.phone])
            .returning(User)
        )
        result = await self._session.scalars(statement)
        return result.one_or_none()
