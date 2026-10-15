from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Account
from payflow.domain.enums import Currency, SystemAccount


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

    async def get_wallet(self, user_id: UUID, currency: Currency) -> Account | None:
        result = await self._session.scalars(
            select(Account).where(
                Account.user_id == user_id, Account.currency == currency
            )
        )
        return result.one_or_none()

    async def system_account(self, code: SystemAccount, currency: Currency) -> Account:
        """Fetch a system account, creating it on first use."""
        lookup = select(Account).where(
            Account.system_code == code, Account.currency == currency
        )
        if account := (await self._session.scalars(lookup)).one_or_none():
            return account
        await self._session.execute(
            insert(Account)
            .values(system_code=code, currency=currency)
            .on_conflict_do_nothing(
                index_elements=[Account.system_code, Account.currency]
            )
        )
        return (await self._session.scalars(lookup)).one()

    async def lock(self, account_ids: Collection[UUID]) -> Sequence[Account]:
        # one statement with ORDER BY takes row locks in id order, so two postings
        # over the same accounts always queue instead of deadlocking
        statement = (
            select(Account)
            .where(Account.id.in_(account_ids))
            .order_by(Account.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self._session.scalars(statement)
        return result.all()
