import asyncio
import random
from collections import Counter
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.core.config import Settings
from payflow.db.models import Account, LedgerEntry, Transaction, User
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.users import UserRepository
from payflow.domain.enums import Currency, TransactionType
from payflow.domain.exceptions import InsufficientFundsError
from payflow.domain.fraud import FraudPolicy
from payflow.domain.services.transfers import TransferCommand, TransferService
from tests.integration.helpers import (
    DAYTIME,
    Sessions,
    balances,
    fund,
    send_transfer,
    sign_up,
)

USERS = 20
TRANSFERS = 1000
OPENING_BALANCE = Decimal("10000.00")


async def create_funded_users(sessions: Sessions) -> list[User]:
    users = []
    async with sessions.begin() as session:
        for index in range(USERS):
            user = await UserRepository(session).create(
                phone=f"+7701{index:07d}", full_name=f"User {index}", password_hash="-"
            )
            assert user is not None
            await AccountRepository(session).open_wallets(user.id)
            users.append(user)
    for user in users:
        await fund(sessions, user.id, str(OPENING_BALANCE))
    return users


def random_plan(users: list[User]) -> list[tuple[User, User, Decimal]]:
    rng = random.Random(1000)
    plan = []
    for _ in range(TRANSFERS):
        sender, recipient = rng.sample(users, 2)
        plan.append((sender, recipient, Decimal(rng.randint(1, 100_000)) / 100))
    return plan


async def ledger_drift(session: AsyncSession) -> list[tuple[str, Decimal, Decimal]]:
    ledger_sum = func.coalesce(func.sum(LedgerEntry.amount), 0)
    rows = await session.execute(
        select(Account.id, Account.balance, ledger_sum)
        .outerjoin(LedgerEntry, LedgerEntry.account_id == Account.id)
        .group_by(Account.id)
        .having(Account.balance != ledger_sum)
    )
    return [(str(account_id), balance, total) for account_id, balance, total in rows]


async def test_parallel_transfers_keep_money_constant(
    session_factory: Sessions, settings: Settings
) -> None:
    users = await create_funded_users(session_factory)
    policy = FraudPolicy.from_settings(settings.fraud)

    async def transfer(sender: User, recipient: User, amount: Decimal) -> str:
        async with session_factory() as session:
            service = TransferService(session, policy, lambda: DAYTIME)
            try:
                await service.transfer(
                    TransferCommand(sender.id, recipient.phone, amount, Currency.KZT)
                )
            except InsufficientFundsError:
                return "insufficient_funds"
            await session.commit()
            return "completed"

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(transfer(*step)) for step in random_plan(users)]
    outcomes = Counter(task.result() for task in tasks)

    assert outcomes.total() == TRANSFERS
    assert outcomes["completed"] > 0
    assert outcomes["insufficient_funds"] > 0
    async with session_factory() as session:
        wallets = (
            await session.scalars(
                select(Account.balance).where(Account.user_id.is_not(None))
            )
        ).all()
        assert sum(wallets) == USERS * OPENING_BALANCE
        assert min(wallets) >= 0
        assert await ledger_drift(session) == []
        assert await session.scalar(select(func.sum(LedgerEntry.amount))) == 0
        assert (
            await session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.type == TransactionType.TRANSFER
                )
            )
            == outcomes["completed"]
        )


async def test_concurrent_retries_with_one_key_execute_once(
    client: AsyncClient, session_factory: Sessions
) -> None:
    alice = await sign_up(client, "+77010000001")
    bob = await sign_up(client, "+77010000002")
    await fund(session_factory, alice.id, "1000.00")

    responses = await asyncio.gather(
        *(
            send_transfer(client, alice, bob.phone, "100.00", key="one-key")
            for _ in range(5)
        )
    )

    assert [r.status_code for r in responses] == [201] * 5
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum(r.headers.get("Idempotent-Replayed") == "true" for r in responses) == 4
    assert (await balances(client, alice))["KZT"] == "900.00"
