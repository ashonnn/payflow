from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from payflow.domain.enums import Currency
from tests.integration.fakes import FakePaymentProvider, FakeRatesProvider
from tests.integration.helpers import (
    ApiUser,
    Sessions,
    fund,
    send_transfer,
    sign_up,
    start_deposit,
)

type Item = tuple[str, str, str, str]


async def history(client: AsyncClient, user: ApiUser, **params: Any) -> dict[str, Any]:
    response = await client.get(
        "/api/v1/transactions", params=params, headers=user.headers
    )
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


def summary(page: dict[str, Any]) -> list[Item]:
    return [
        (item["type"], item["direction"], item["status"], item["amount"])
        for item in page["items"]
    ]


@pytest.fixture
async def parties(
    client: AsyncClient,
    session_factory: Sessions,
    payment_provider: FakePaymentProvider,
    rates_provider: FakeRatesProvider,
) -> tuple[ApiUser, ApiUser]:
    alice = await sign_up(client, "+77010000001")
    bob = await sign_up(client, "+77010000002")
    await fund(session_factory, alice.id, "2000000.00")
    await fund(session_factory, bob.id, "1500000.00")
    await send_transfer(client, alice, bob.phone, "1000.00")
    await send_transfer(client, bob, alice.phone, "300.00")
    await client.post(
        "/api/v1/exchanges",
        json={"from_currency": "KZT", "to_currency": "USD", "amount": "5000.00"},
        headers={**alice.headers, "Idempotency-Key": str(uuid4())},
    )
    await start_deposit(client, alice, "750.00")
    await send_transfer(client, alice, bob.phone, "1200000.00")
    await send_transfer(client, bob, alice.phone, "1100000.00")
    return alice, bob


ALICE_FEED: list[Item] = [
    ("transfer", "outgoing", "pending_review", "1200000.00"),
    ("deposit", "incoming", "pending", "750.00"),
    ("exchange", "internal", "completed", "5000.00"),
    ("transfer", "incoming", "completed", "300.00"),
    ("transfer", "outgoing", "completed", "1000.00"),
    ("deposit", "incoming", "completed", "2000000.00"),
]


async def test_history_lists_visible_items_newest_first(
    client: AsyncClient, parties: tuple[ApiUser, ApiUser]
) -> None:
    alice, _ = parties

    page = await history(client, alice)

    assert summary(page) == ALICE_FEED
    assert page["next_cursor"] is None


async def test_held_transfers_are_hidden_from_recipients(
    client: AsyncClient, parties: tuple[ApiUser, ApiUser]
) -> None:
    _, bob = parties

    page = await history(client, bob)

    assert ("transfer", "incoming", "pending_review", "1200000.00") not in summary(page)
    assert ("transfer", "outgoing", "pending_review", "1100000.00") in summary(page)


async def test_cursor_pagination_visits_each_item_once(
    client: AsyncClient, parties: tuple[ApiUser, ApiUser]
) -> None:
    alice, _ = parties
    seen: list[Item] = []
    cursor = None

    for _ in range(10):
        params = {"limit": 4} | ({"cursor": cursor} if cursor else {})
        page = await history(client, alice, **params)
        seen.extend(summary(page))
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == ALICE_FEED


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"type": "transfer"}, [0, 3, 4]),
        ({"direction": "incoming"}, [1, 3, 5]),
        ({"direction": "outgoing", "status": "completed"}, [4]),
        ({"direction": "internal"}, [2]),
        ({"currency": "USD"}, [2]),
        ({"status": "pending"}, [1]),
        ({"min_amount": "500", "max_amount": "5000"}, [1, 2, 4]),
        ({"created_from": "2999-01-01T00:00:00Z"}, []),
    ],
)
async def test_filters_narrow_the_feed(
    client: AsyncClient,
    parties: tuple[ApiUser, ApiUser],
    params: dict[str, str],
    expected: list[int],
) -> None:
    alice, _ = parties

    page = await history(client, alice, **params)

    assert summary(page) == [ALICE_FEED[index] for index in expected]


async def test_currency_filter_matches_either_side_of_an_exchange(
    client: AsyncClient, parties: tuple[ApiUser, ApiUser]
) -> None:
    alice, _ = parties

    page = await history(client, alice, currency=Currency.KZT, direction="internal")

    assert summary(page) == [ALICE_FEED[2]]


@pytest.mark.parametrize(
    ("params", "status_code"),
    [
        ({"cursor": "not-a-cursor"}, 400),
        ({"created_from": "2026-10-15T00:00:00"}, 422),
        ({"min_amount": "10", "max_amount": "5"}, 422),
        ({"limit": "0"}, 422),
        ({"unknown": "1"}, 422),
    ],
)
async def test_bad_queries_are_rejected(
    client: AsyncClient, params: dict[str, str], status_code: int
) -> None:
    user = await sign_up(client, "+77010000003")

    response = await client.get(
        "/api/v1/transactions", params=params, headers=user.headers
    )

    assert response.status_code == status_code
