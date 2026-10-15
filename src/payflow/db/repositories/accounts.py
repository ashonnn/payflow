from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Account
from payflow.domain.enums import Currency


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open_wallets(self, user_id: UUID) -> list[Account]:
        wallets = [Account(user_id=user_id, currency=currency) for currency in Currency]
        self._session.add_all(wallets)
        await self._session.flush()
        return wallets

    async def list_for_user(self, user_id: UUID) -> Sequence[Account]:
        result = await self._session.scalars(
            select(Account).where(Account.user_id == user_id).order_by(Account.currency)
        )
        return result.all()
