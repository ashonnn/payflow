import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mock_provider.gateway import SIGNATURE_HEADER, sign
from payflow.core.clock import utc_now
from payflow.db.models import User
from payflow.domain.enums import Currency
from payflow.domain.services.deposits import DepositService
from tests.integration.fakes import FakePaymentProvider

DEFAULT_PASSWORD = "correct-horse-battery"
WEBHOOK_PATH = "/api/v1/webhooks/payment-provider"
# noon in Almaty, clear of the night-time fraud window
DAYTIME = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
# 02:30 in Almaty
NIGHT = datetime(2026, 10, 14, 21, 30, tzinfo=UTC)

Sessions = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class ApiUser:
    id: UUID
    phone: str
    headers: dict[str, str]


async def sign_up(
    client: AsyncClient,
    phone: str,
    *,
    full_name: str = "Test User",
    password: str = DEFAULT_PASSWORD,
) -> ApiUser:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": password, "full_name": full_name},
    )
    assert registered.status_code == 201, registered.text
    tokens = await client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": password}
    )
    assert tokens.status_code == 200, tokens.text
    return ApiUser(
        id=UUID(registered.json()["id"]),
        phone=registered.json()["phone"],
        headers={"Authorization": f"Bearer {tokens.json()['access_token']}"},
    )


async def fund(
    sessions: Sessions,
    user_id: UUID,
    amount: str,
    currency: Currency = Currency.KZT,
) -> None:
    async with sessions.begin() as session:
        deposits = DepositService(session, FakePaymentProvider(), utc_now)
        await deposits.credit_settled(
            user_id, currency, Decimal(amount), external_id=f"test-{uuid4().hex}"
        )


async def make_admin(sessions: Sessions, user_id: UUID) -> None:
    async with sessions.begin() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(is_admin=True)
        )


async def balances(client: AsyncClient, user: ApiUser) -> dict[str, str]:
    accounts = (await client.get("/api/v1/accounts", headers=user.headers)).json()
    return {account["currency"]: account["balance"] for account in accounts}


async def send_transfer(
    client: AsyncClient,
    sender: ApiUser,
    to_phone: str,
    amount: str,
    currency: str = "KZT",
    *,
    key: str | None = None,
    comment: str | None = None,
) -> Response:
    return await client.post(
        "/api/v1/transfers",
        json={
            "to_phone": to_phone,
            "amount": amount,
            "currency": currency,
            "comment": comment,
        },
        headers={**sender.headers, "Idempotency-Key": key or str(uuid4())},
    )


async def start_deposit(
    client: AsyncClient,
    user: ApiUser,
    amount: str = "1500.00",
    currency: str = "KZT",
    *,
    key: str | None = None,
) -> Response:
    return await client.post(
        "/api/v1/deposits",
        json={"currency": currency, "amount": amount},
        headers={**user.headers, "Idempotency-Key": key or str(uuid4())},
    )


def payment_event(
    payment_id: str,
    status: str,
    amount: str,
    currency: str = "KZT",
    *,
    event_id: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid4().hex}",
        "type": f"payment.{status}",
        "created": int(time.time()),
        "data": {
            "id": payment_id,
            "reference": "unused",
            "amount": amount,
            "currency": currency,
            "status": status,
            "failure_reason": failure_reason,
        },
    }


async def send_webhook(
    client: AsyncClient, secret: str, event: dict[str, Any]
) -> Response:
    body = json.dumps(event).encode()
    return await client.post(
        WEBHOOK_PATH,
        content=body,
        headers={
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(secret, body, int(time.time())),
        },
    )
