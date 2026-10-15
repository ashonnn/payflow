import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from payflow.cli import main
from payflow.container import Container
from payflow.core.config import Settings, get_settings
from payflow.db.models import Account, LedgerEntry, ReconciliationReport, Transaction
from payflow.domain.enums import Currency, ReconciliationStatus
from payflow.workers.jobs import reconcile
from payflow.workers.locks import advisory_lock
from tests.integration.helpers import Sessions, fund, send_transfer, sign_up


@pytest.fixture
async def busy_ledger(client: AsyncClient, session_factory: Sessions) -> UUID:
    alice = await sign_up(client, "+77010000001")
    bob = await sign_up(client, "+77010000002")
    await fund(session_factory, alice.id, "5000.00")
    await send_transfer(client, alice, bob.phone, "1200.00")
    await send_transfer(client, bob, alice.phone, "200.00")
    return alice.id


async def wallet_id(sessions: Sessions, user_id: UUID) -> UUID:
    async with sessions() as session:
        wallet = await session.scalar(
            select(Account.id).where(
                Account.user_id == user_id, Account.currency == Currency.KZT
            )
        )
        assert wallet is not None
        return wallet


@asynccontextmanager
async def balance_trigger_disabled(engine: AsyncEngine) -> AsyncIterator[None]:
    statement = "ALTER TABLE ledger_entries {} TRIGGER ledger_entries_balanced"
    async with engine.begin() as connection:
        await connection.execute(text(statement.format("DISABLE")))
    try:
        yield
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(statement.format("ENABLE")))


async def test_clean_ledger_reconciles(
    container: Container, busy_ledger: UUID, session_factory: Sessions
) -> None:
    report = await reconcile(container)

    assert report is not None
    assert report.status is ReconciliationStatus.OK
    assert report.issues == []
    assert report.accounts_checked == 5
    async with session_factory() as session:
        stored = await session.scalars(select(ReconciliationReport))
        assert [r.status for r in stored] == [ReconciliationStatus.OK]


async def test_edited_balance_is_reported_as_drift(
    container: Container, busy_ledger: UUID, session_factory: Sessions
) -> None:
    wallet = await wallet_id(session_factory, busy_ledger)
    async with session_factory.begin() as session:
        await session.execute(
            update(Account)
            .where(Account.id == wallet)
            .values(balance=Account.balance + 1)
        )

    report = await reconcile(container)

    assert report is not None
    assert report.status is ReconciliationStatus.MISMATCH
    assert report.issues == [
        {
            "kind": "balance_drift",
            "account_id": str(wallet),
            "currency": "KZT",
            "stored_balance": "4001.00",
            "ledger_balance": "4000.00",
        }
    ]


async def test_unbalanced_entries_are_reported(
    container: Container,
    busy_ledger: UUID,
    session_factory: Sessions,
    engine: AsyncEngine,
) -> None:
    wallet = await wallet_id(session_factory, busy_ledger)
    async with balance_trigger_disabled(engine), session_factory.begin() as session:
        transaction_id = await session.scalar(select(Transaction.id).limit(1))
        assert transaction_id is not None
        session.add(
            LedgerEntry(
                transaction_id=transaction_id,
                account_id=wallet,
                currency=Currency.KZT,
                amount=Decimal("10.00"),
            )
        )

    report = await reconcile(container)

    assert report is not None
    assert {issue["kind"] for issue in report.issues} == {
        "balance_drift",
        "unbalanced_transaction",
        "nonzero_currency_total",
    }


async def test_concurrent_run_is_skipped(container: Container) -> None:
    async with advisory_lock(container.engine, "reconciliation") as acquired:
        skipped = await reconcile(container)

    assert acquired
    assert skipped is None


async def test_reconcile_command_exit_code(
    busy_ledger: UUID,
    session_factory: Sessions,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "DATABASE_URL": settings.database_url,
        "REDIS_URL": settings.redis_url,
        "JWT_SECRET": settings.jwt_secret.get_secret_value(),
        "ADMIN_SESSION_SECRET": "unused",
        "PAYMENT_PROVIDER_URL": "http://unused",
        "PAYMENT_PROVIDER_API_KEY": "unused",
        "PAYMENT_PROVIDER_WEBHOOK_SECRET": "unused",
        "FX_PROVIDER_URL": "http://unused",
        "LOG_JSON": "false",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        healthy = await asyncio.to_thread(main, ["reconcile"])
        wallet = await wallet_id(session_factory, busy_ledger)
        async with session_factory.begin() as session:
            await session.execute(
                update(Account).where(Account.id == wallet).values(balance=0)
            )
        broken = await asyncio.to_thread(main, ["reconcile"])
    finally:
        get_settings.cache_clear()

    assert (healthy, broken) == (0, 1)
