from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from payflow.workers.outbox import OutboxRelay
from payflow.workers.runner import notify
from tests.integration.fakes import FakeRatesProvider
from tests.integration.helpers import (
    ApiUser,
    Sessions,
    fund,
    make_admin,
    send_transfer,
    sign_up,
)


@pytest.fixture
async def alice(client: AsyncClient, session_factory: Sessions) -> ApiUser:
    user = await sign_up(client, "+77010000001")
    await fund(session_factory, user.id, "2000000.00")
    return user


@pytest.fixture
async def bob(client: AsyncClient) -> ApiUser:
    return await sign_up(client, "+77010000002")


async def deliver(sessions: Sessions) -> None:
    relay = OutboxRelay(
        sessions,
        notify,
        batch_size=100,
        max_attempts=3,
        retry_base=timedelta(0),
        poll_interval=timedelta(0),
    )
    await relay.run_once()


async def messages(client: AsyncClient, user: ApiUser, **params: int) -> list[str]:
    response = await client.get(
        "/api/v1/notifications", params=params, headers=user.headers
    )
    return [item["message"] for item in response.json()]


async def test_both_sides_of_a_transfer_are_notified(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    await send_transfer(client, alice, bob.phone, "2500.00")

    await deliver(session_factory)

    assert await messages(client, alice) == [
        "You sent 2,500.00 KZT to +7701***0002",
        "2,000,000.00 KZT was added to your wallet",
    ]
    assert await messages(client, bob) == [
        "You received 2,500.00 KZT from +7701***0001"
    ]


async def test_review_outcome_is_notified(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    admin = await sign_up(client, "+77000000000")
    await make_admin(session_factory, admin.id)
    held = await send_transfer(client, alice, bob.phone, "1500000.00")
    await client.post(
        f"/api/v1/admin/reviews/{held.json()['id']}/reject",
        json={"reason": "suspicious"},
        headers=admin.headers,
    )

    await deliver(session_factory)

    assert (await messages(client, alice))[:2] == [
        "Your transfer of 1,500,000.00 KZT was declined and refunded",
        "Your transfer of 1,500,000.00 KZT is under review",
    ]
    assert await messages(client, bob) == []


async def test_exchange_is_notified(
    client: AsyncClient,
    alice: ApiUser,
    session_factory: Sessions,
    rates_provider: FakeRatesProvider,
) -> None:
    await client.post(
        "/api/v1/exchanges",
        json={"from_currency": "KZT", "to_currency": "USD", "amount": "10000.00"},
        headers={**alice.headers, "Idempotency-Key": str(uuid4())},
    )

    await deliver(session_factory)

    assert (await messages(client, alice))[
        0
    ] == "You exchanged 10,000.00 KZT for 19.90 USD"


async def test_notifications_page_backwards(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    for amount in ("1.00", "2.00", "3.00"):
        await send_transfer(client, alice, bob.phone, amount)
    await deliver(session_factory)
    newest = (
        await client.get(
            "/api/v1/notifications", params={"limit": 2}, headers=alice.headers
        )
    ).json()

    older = await messages(client, alice, before_id=newest[-1]["id"])

    assert [item["message"] for item in newest] == [
        "You sent 3.00 KZT to +7701***0002",
        "You sent 2.00 KZT to +7701***0002",
    ]
    assert older == [
        "You sent 1.00 KZT to +7701***0002",
        "2,000,000.00 KZT was added to your wallet",
    ]
