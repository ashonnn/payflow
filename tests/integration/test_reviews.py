from decimal import Decimal

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select

from payflow.container import Container
from payflow.db.models import Account
from payflow.domain.enums import Currency, SystemAccount
from tests.integration.helpers import (
    DAYTIME,
    NIGHT,
    ApiUser,
    Sessions,
    balances,
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


@pytest.fixture
async def admin(client: AsyncClient, session_factory: Sessions) -> ApiUser:
    user = await sign_up(client, "+77000000000")
    await make_admin(session_factory, user.id)
    return user


async def hold_balance(sessions: Sessions) -> Decimal:
    async with sessions() as session:
        balance = await session.scalar(
            select(Account.balance).where(
                Account.system_code == SystemAccount.REVIEW_HOLD,
                Account.currency == Currency.KZT,
            )
        )
        return balance or Decimal(0)


async def held_transfer(client: AsyncClient, alice: ApiUser, bob: ApiUser) -> Response:
    response = await send_transfer(client, alice, bob.phone, "1500000.00")
    assert response.json()["status"] == "pending_review"
    return response


async def test_large_transfer_is_held_until_review(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, session_factory: Sessions
) -> None:
    response = await held_transfer(client, alice, bob)

    assert response.status_code == 201
    assert response.json()["review_reasons"] == ["large_amount", "new_recipient"]
    assert (await balances(client, alice))["KZT"] == "500000.00"
    assert (await balances(client, bob))["KZT"] == "0.00"
    assert await hold_balance(session_factory) == Decimal("1500000.00")
    hidden = await client.get(
        f"/api/v1/transactions/{response.json()['id']}", headers=bob.headers
    )
    assert hidden.status_code == 404


async def test_new_recipient_at_night_is_held(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, container: Container
) -> None:
    container.clock = lambda: NIGHT

    response = await send_transfer(client, alice, bob.phone, "100.00")

    assert response.json()["status"] == "pending_review"
    assert response.json()["review_reasons"] == ["new_recipient", "night_time"]


async def test_known_recipient_at_night_is_not_held(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, container: Container
) -> None:
    await send_transfer(client, alice, bob.phone, "100.00")
    container.clock = lambda: NIGHT

    response = await send_transfer(client, alice, bob.phone, "100.00")

    assert response.json()["status"] == "completed"
    container.clock = lambda: DAYTIME


async def test_approval_releases_hold_to_recipient(
    client: AsyncClient,
    alice: ApiUser,
    bob: ApiUser,
    admin: ApiUser,
    session_factory: Sessions,
) -> None:
    transfer_id = (await held_transfer(client, alice, bob)).json()["id"]

    response = await client.post(
        f"/api/v1/admin/reviews/{transfer_id}/approve", headers=admin.headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert (await balances(client, bob))["KZT"] == "1500000.00"
    assert await hold_balance(session_factory) == Decimal(0)
    seen_by_bob = await client.get(
        f"/api/v1/transactions/{transfer_id}", headers=bob.headers
    )
    assert seen_by_bob.json()["review_reasons"] is None


async def test_rejection_returns_funds_to_sender(
    client: AsyncClient,
    alice: ApiUser,
    bob: ApiUser,
    admin: ApiUser,
    session_factory: Sessions,
) -> None:
    transfer_id = (await held_transfer(client, alice, bob)).json()["id"]

    response = await client.post(
        f"/api/v1/admin/reviews/{transfer_id}/reject",
        json={"reason": "recipient flagged by compliance"},
        headers=admin.headers,
    )

    assert response.json()["status"] == "rejected"
    assert response.json()["failure_reason"] == "recipient flagged by compliance"
    assert (await balances(client, alice))["KZT"] == "2000000.00"
    assert await hold_balance(session_factory) == Decimal(0)


async def test_transfer_can_be_reviewed_only_once(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, admin: ApiUser
) -> None:
    transfer_id = (await held_transfer(client, alice, bob)).json()["id"]
    url = f"/api/v1/admin/reviews/{transfer_id}"

    await client.post(f"{url}/approve", headers=admin.headers)
    again = await client.post(
        f"{url}/reject", json={"reason": "too late"}, headers=admin.headers
    )

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "not_reviewable"


async def test_pending_reviews_are_listed_for_admins(
    client: AsyncClient, alice: ApiUser, bob: ApiUser, admin: ApiUser
) -> None:
    transfer_id = (await held_transfer(client, alice, bob)).json()["id"]

    response = await client.get("/api/v1/admin/reviews", headers=admin.headers)

    assert [item["id"] for item in response.json()] == [transfer_id]
    assert response.json()[0]["sender_phone"] == alice.phone
    assert response.json()[0]["recipient_phone"] == bob.phone


async def test_review_endpoints_require_admin(
    client: AsyncClient, alice: ApiUser
) -> None:
    response = await client.get("/api/v1/admin/reviews", headers=alice.headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"
