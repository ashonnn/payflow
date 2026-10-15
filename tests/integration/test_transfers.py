import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from payflow.container import Container
from payflow.db.models import Transaction, User
from payflow.domain.enums import Currency, TransactionType
from tests.integration.helpers import (
    ApiUser,
    Sessions,
    balances,
    fund,
    send_transfer,
    sign_up,
)


@pytest.fixture
async def alice(client: AsyncClient, session_factory: Sessions) -> ApiUser:
    user = await sign_up(client, "+77010000001", full_name="Alice")
    await fund(session_factory, user.id, "10000.00")
    return user


@pytest.fixture
async def bob(client: AsyncClient) -> ApiUser:
    return await sign_up(client, "+77010000002", full_name="Bob")


async def count_transfers(sessions: Sessions) -> int:
    async with sessions() as session:
        total = await session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.type == TransactionType.TRANSFER
            )
        )
        return total or 0


async def test_transfer_moves_money_between_wallets(
    client: AsyncClient, alice: ApiUser, bob: ApiUser
) -> None:
    response = await send_transfer(client, alice, bob.phone, "2500.00", comment="lunch")

    assert response.status_code == 201
    sent = response.json()
    assert sent["status"] == "completed"
    assert sent["direction"] == "outgoing"
    assert sent["counterparty_phone"] == bob.phone
    assert sent["comment"] == "lunch"
    assert (await balances(client, alice))["KZT"] == "7500.00"
    assert (await balances(client, bob))["KZT"] == "2500.00"

    received = await client.get(
        f"/api/v1/transactions/{sent['id']}", headers=bob.headers
    )
    assert received.json()["direction"] == "incoming"
    assert received.json()["counterparty_phone"] == alice.phone


async def test_recipient_phone_is_normalized(
    client: AsyncClient, alice: ApiUser, bob: ApiUser
) -> None:
    response = await send_transfer(client, alice, "8 (701) 000-00-02", "10")

    assert response.status_code == 201
    assert response.json()["counterparty_phone"] == bob.phone


async def test_usd_wallets_are_separate(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    await fund(session_factory, alice.id, "100.00", Currency.USD)

    response = await send_transfer(client, alice, bob.phone, "40.00", currency="USD")

    assert response.status_code == 201
    assert await balances(client, alice) == {"KZT": "10000.00", "USD": "60.00"}
    assert await balances(client, bob) == {"KZT": "0.00", "USD": "40.00"}


async def test_insufficient_funds_leave_no_trace(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    response = await send_transfer(client, alice, bob.phone, "10000.01")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_funds"
    assert (await balances(client, alice))["KZT"] == "10000.00"
    assert await count_transfers(session_factory) == 0


async def test_unknown_and_deactivated_recipients_are_rejected(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    unknown = await send_transfer(client, alice, "+77019999999", "10")
    async with session_factory.begin() as session:
        await session.execute(
            update(User).where(User.id == bob.id).values(is_active=False)
        )
    deactivated = await send_transfer(client, alice, bob.phone, "10")

    assert unknown.status_code == 404
    assert deactivated.status_code == 404
    assert deactivated.json()["error"]["code"] == "recipient_not_found"


async def test_self_transfer_is_rejected(client: AsyncClient, alice: ApiUser) -> None:
    response = await send_transfer(client, alice, alice.phone, "10")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "self_transfer"


async def test_retry_with_same_key_moves_money_once(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    first = await send_transfer(client, alice, bob.phone, "1000", key="transfer-1")
    retry = await send_transfer(client, alice, bob.phone, "1000", key="transfer-1")

    assert retry.json() == first.json()
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert (await balances(client, alice))["KZT"] == "9000.00"
    assert await count_transfers(session_factory) == 1


async def test_transfers_are_rate_limited_per_user(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, container: Container
) -> None:
    limit = container.settings.transfer_rate_limit

    responses = [
        await send_transfer(client, alice, bob.phone, "1.00") for _ in range(limit + 1)
    ]

    assert [r.status_code for r in responses[:limit]] == [201] * limit
    limited = responses[-1]
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 0 < int(limited.headers["Retry-After"]) <= 60
    assert (await send_transfer(client, bob, alice.phone, "1.00")).status_code == 201
