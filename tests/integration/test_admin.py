from uuid import UUID

import pytest
from httpx import AsyncClient

from payflow.api.admin import VIEWS
from payflow.db.models import Transaction
from payflow.domain.enums import TransactionStatus
from tests.integration.helpers import (
    DEFAULT_PASSWORD,
    ApiUser,
    Sessions,
    fund,
    make_admin,
    send_transfer,
    sign_up,
)


@pytest.fixture
async def admin(client: AsyncClient, session_factory: Sessions) -> ApiUser:
    user = await sign_up(client, "+77000000000")
    await make_admin(session_factory, user.id)
    return user


@pytest.fixture
async def held_transfer(client: AsyncClient, session_factory: Sessions) -> UUID:
    alice = await sign_up(client, "+77010000001")
    bob = await sign_up(client, "+77010000002")
    await fund(session_factory, alice.id, "2000000.00")
    response = await send_transfer(client, alice, bob.phone, "1500000.00")
    return UUID(response.json()["id"])


async def admin_login(client: AsyncClient, phone: str) -> int:
    response = await client.post(
        "/admin/login", data={"username": phone, "password": DEFAULT_PASSWORD}
    )
    return response.status_code


async def status_of(sessions: Sessions, transaction_id: UUID) -> TransactionStatus:
    async with sessions() as session:
        transaction = await session.get(Transaction, transaction_id)
        assert transaction is not None
        return transaction.status


async def test_admin_requires_login(client: AsyncClient) -> None:
    response = await client.get("/admin/")

    assert response.status_code == 302
    assert response.headers["location"].endswith("/admin/login")


async def test_regular_users_cannot_log_in(client: AsyncClient) -> None:
    user = await sign_up(client, "+77010000009")

    assert await admin_login(client, user.phone) == 400


async def test_every_view_renders(
    client: AsyncClient, admin: ApiUser, held_transfer: UUID
) -> None:
    assert await admin_login(client, admin.phone) == 302

    for view in VIEWS:
        listing = await client.get(f"/admin/{view.identity}/list")
        assert listing.status_code == 200, view.identity
    detail = await client.get(f"/admin/transaction/details/{held_transfer}")
    assert detail.status_code == 200


async def test_held_transfer_can_be_approved(
    client: AsyncClient, admin: ApiUser, held_transfer: UUID, session_factory: Sessions
) -> None:
    await admin_login(client, admin.phone)

    response = await client.get(
        "/admin/transaction/action/approve", params={"pks": str(held_transfer)}
    )

    assert response.status_code == 302
    assert (
        await status_of(session_factory, held_transfer) is TransactionStatus.COMPLETED
    )


async def test_held_transfer_can_be_rejected(
    client: AsyncClient, admin: ApiUser, held_transfer: UUID, session_factory: Sessions
) -> None:
    await admin_login(client, admin.phone)

    await client.get(
        "/admin/transaction/action/reject", params={"pks": str(held_transfer)}
    )

    assert await status_of(session_factory, held_transfer) is TransactionStatus.REJECTED


async def test_settled_transfer_is_left_alone(
    client: AsyncClient, admin: ApiUser, held_transfer: UUID, session_factory: Sessions
) -> None:
    await admin_login(client, admin.phone)
    approve = "/admin/transaction/action/approve"
    await client.get(approve, params={"pks": str(held_transfer)})

    again = await client.get(
        "/admin/transaction/action/reject", params={"pks": str(held_transfer)}
    )

    assert again.status_code == 302
    assert (
        await status_of(session_factory, held_transfer) is TransactionStatus.COMPLETED
    )
