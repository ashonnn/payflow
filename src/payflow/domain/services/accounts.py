from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Account
from payflow.db.repositories.accounts import AccountRepository


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self._accounts = AccountRepository(session)

    async def list_wallets(self, user_id: UUID) -> Sequence[Account]:
        return await self._accounts.list_for_user(user_id)
