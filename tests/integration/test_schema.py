from decimal import Decimal
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from payflow.db.base import Base
from payflow.db.models import Account, LedgerEntry, Transaction, User
from payflow.domain.enums import (
    Currency,
    SystemAccount,
    TransactionStatus,
    TransactionType,
)


async def create_deposit(
    session: AsyncSession, currency: Currency = Currency.KZT
) -> tuple[Account, Account, Transaction]:
    user = User(phone="+77010000001", full_name="Aigerim", password_hash="unused")
    wallet = Account(user=user, currency=currency)
    clearing = Account(system_code=SystemAccount.PROVIDER_CLEARING, currency=currency)
    session.add_all([user, wallet, clearing])
    await session.flush()
    transaction = Transaction(
        type=TransactionType.DEPOSIT,
        status=TransactionStatus.COMPLETED,
        initiator_id=user.id,
        destination_account_id=wallet.id,
        amount=Decimal("100.00"),
        currency=currency,
    )
    session.add(transaction)
    await session.flush()
    return wallet, clearing, transaction


def entry(account: Account, transaction: Transaction, amount: str) -> LedgerEntry:
    return LedgerEntry(
        transaction_id=transaction.id,
        account_id=account.id,
        currency=account.currency,
        amount=Decimal(amount),
    )


async def test_migrations_match_models(engine: AsyncEngine) -> None:
    def diff(connection: Connection) -> list[Any]:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return list(compare_metadata(context, Base.metadata))

    async with engine.connect() as connection:
        assert await connection.run_sync(diff) == []


async def test_balanced_entries_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        wallet, clearing, transaction = await create_deposit(session)
        session.add_all(
            [
                entry(wallet, transaction, "100.00"),
                entry(clearing, transaction, "-100.00"),
            ]
        )
        await session.commit()


async def test_unbalanced_entries_are_rejected_at_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        wallet, clearing, transaction = await create_deposit(session)
        session.add_all(
            [
                entry(wallet, transaction, "100.00"),
                entry(clearing, transaction, "-99.99"),
            ]
        )
        await session.flush()
        with pytest.raises(IntegrityError, match="do not balance"):
            await session.commit()


async def test_ledger_entries_are_append_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        wallet, clearing, transaction = await create_deposit(session)
        session.add_all(
            [
                entry(wallet, transaction, "100.00"),
                entry(clearing, transaction, "-100.00"),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(update(LedgerEntry).values(amount=Decimal("1.00")))
    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(delete(LedgerEntry))


async def test_user_balance_cannot_go_negative(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        wallet, clearing, _ = await create_deposit(session)
        clearing.balance = Decimal("-50.00")
        await session.flush()
        wallet.balance = Decimal("-0.01")
        with pytest.raises(IntegrityError, match="user_balance_not_negative"):
            await session.flush()


async def test_entry_currency_must_match_account(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        wallet, _, transaction = await create_deposit(session)
        session.add(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=wallet.id,
                currency=Currency.USD,
                amount=Decimal("1.00"),
            )
        )
        with pytest.raises(
            IntegrityError, match="fk_ledger_entries_account_id_accounts"
        ):
            await session.flush()
