from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.db.models import LedgerEntry, OutboxEvent, Transaction
from payflow.domain.enums import EventType, TransactionStatus
from tests.integration.fakes import FakePaymentProvider
from tests.integration.helpers import (
    ApiUser,
    payment_event,
    send_webhook,
    sign_up,
    start_deposit,
)

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
async def user(client: AsyncClient) -> ApiUser:
    return await sign_up(client, "+77011112233")


async def kzt_balance(client: AsyncClient, user: ApiUser) -> str:
    accounts = (await client.get("/api/v1/accounts", headers=user.headers)).json()
    return str(next(a["balance"] for a in accounts if a["currency"] == "KZT"))


async def load_transaction(sessions: Sessions, transaction_id: str) -> Transaction:
    async with sessions() as session:
        transaction = await session.get(Transaction, UUID(transaction_id))
        assert transaction is not None
        return transaction


async def ledger_amounts(sessions: Sessions, transaction_id: str) -> list[Decimal]:
    async with sessions() as session:
        result = await session.scalars(
            select(LedgerEntry.amount)
            .where(LedgerEntry.transaction_id == UUID(transaction_id))
            .order_by(LedgerEntry.amount)
        )
        return list(result)


async def outbox_types(sessions: Sessions) -> list[EventType]:
    async with sessions() as session:
        result = await session.scalars(
            select(OutboxEvent.event_type).order_by(OutboxEvent.id)
        )
        return list(result)


async def test_deposit_requires_idempotency_key(
    client: AsyncClient, user: ApiUser, payment_provider: FakePaymentProvider
) -> None:
    response = await client.post(
        "/api/v1/deposits",
        json={"currency": "KZT", "amount": "100.00"},
        headers=user.headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"
    assert payment_provider.calls == []


async def test_deposit_starts_a_pending_provider_payment(
    client: AsyncClient, user: ApiUser, payment_provider: FakePaymentProvider
) -> None:
    response = await start_deposit(client, user, "1500")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["direction"] == "incoming"
    assert body["amount"] == "1500.00"
    assert body["provider_payment_id"].startswith("pay_")
    assert [call.amount for call in payment_provider.calls] == [Decimal("1500.00")]
    assert payment_provider.calls[0].reference == body["id"]


async def test_retry_with_same_key_replays_first_response(
    client: AsyncClient,
    user: ApiUser,
    payment_provider: FakePaymentProvider,
    session_factory: Sessions,
) -> None:
    first = await start_deposit(client, user, key="deposit-1")
    retry = await start_deposit(client, user, key="deposit-1")

    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert len(payment_provider.calls) == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Transaction.id))) == 1


async def test_key_reused_with_different_payload_is_rejected(
    client: AsyncClient, user: ApiUser, payment_provider: FakePaymentProvider
) -> None:
    await start_deposit(client, user, "100.00", key="deposit-1")

    response = await start_deposit(client, user, "200.00", key="deposit-1")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"


async def test_keys_are_scoped_per_user(
    client: AsyncClient, user: ApiUser, payment_provider: FakePaymentProvider
) -> None:
    other = await sign_up(client, "+77019998877")

    mine = await start_deposit(client, user, key="shared-key")
    theirs = await start_deposit(client, other, key="shared-key")

    assert theirs.status_code == 201
    assert theirs.json()["id"] != mine.json()["id"]


async def test_provider_outage_is_reported_and_key_stays_usable(
    client: AsyncClient, user: ApiUser, payment_provider: FakePaymentProvider
) -> None:
    payment_provider.available = False
    failed = await start_deposit(client, user, key="deposit-1")
    payment_provider.available = True
    retried = await start_deposit(client, user, key="deposit-1")

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "payment_provider_unavailable"
    assert retried.status_code == 201
    assert "Idempotent-Replayed" not in retried.headers


async def test_successful_payment_credits_wallet_through_ledger(
    client: AsyncClient,
    user: ApiUser,
    payment_provider: FakePaymentProvider,
    webhook_secret: str,
    session_factory: Sessions,
) -> None:
    deposit = (await start_deposit(client, user, "1500.00")).json()

    response = await send_webhook(
        client,
        webhook_secret,
        payment_event(deposit["provider_payment_id"], "succeeded", "1500.00"),
    )

    assert response.status_code == 200
    assert await kzt_balance(client, user) == "1500.00"
    transaction = await load_transaction(session_factory, deposit["id"])
    assert transaction.status is TransactionStatus.COMPLETED
    assert transaction.completed_at is not None
    assert await ledger_amounts(session_factory, deposit["id"]) == [
        Decimal("-1500.00"),
        Decimal("1500.00"),
    ]
    assert await outbox_types(session_factory) == [EventType.DEPOSIT_COMPLETED]


async def test_redelivered_and_late_events_are_applied_once(
    client: AsyncClient,
    user: ApiUser,
    payment_provider: FakePaymentProvider,
    webhook_secret: str,
    session_factory: Sessions,
) -> None:
    deposit = (await start_deposit(client, user, "700.00")).json()
    payment_id = deposit["provider_payment_id"]
    event = payment_event(payment_id, "succeeded", "700.00", event_id="evt_1")

    responses = [
        await send_webhook(client, webhook_secret, event),
        await send_webhook(client, webhook_secret, event),
        await send_webhook(
            client, webhook_secret, payment_event(payment_id, "succeeded", "700.00")
        ),
    ]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert await kzt_balance(client, user) == "700.00"
    assert len(await ledger_amounts(session_factory, deposit["id"])) == 2


async def test_failed_payment_marks_deposit_failed(
    client: AsyncClient,
    user: ApiUser,
    payment_provider: FakePaymentProvider,
    webhook_secret: str,
    session_factory: Sessions,
) -> None:
    deposit = (await start_deposit(client, user, "50.00")).json()

    await send_webhook(
        client,
        webhook_secret,
        payment_event(
            deposit["provider_payment_id"],
            "failed",
            "50.00",
            failure_reason="card declined",
        ),
    )

    transaction = await load_transaction(session_factory, deposit["id"])
    assert transaction.status is TransactionStatus.FAILED
    assert transaction.failure_reason == "card declined"
    assert await kzt_balance(client, user) == "0.00"
    assert await ledger_amounts(session_factory, deposit["id"]) == []
    assert await outbox_types(session_factory) == [EventType.DEPOSIT_FAILED]


async def test_mismatched_amount_fails_the_deposit(
    client: AsyncClient,
    user: ApiUser,
    payment_provider: FakePaymentProvider,
    webhook_secret: str,
    session_factory: Sessions,
) -> None:
    deposit = (await start_deposit(client, user, "50.00")).json()

    await send_webhook(
        client,
        webhook_secret,
        payment_event(deposit["provider_payment_id"], "succeeded", "5000.00"),
    )

    transaction = await load_transaction(session_factory, deposit["id"])
    assert transaction.status is TransactionStatus.FAILED
    assert await kzt_balance(client, user) == "0.00"


async def test_event_for_unknown_payment_can_be_retried(
    client: AsyncClient,
    user: ApiUser,
    payment_provider: FakePaymentProvider,
    webhook_secret: str,
) -> None:
    early = payment_event("pay_unknown", "succeeded", "10.00", event_id="evt_early")

    response = await send_webhook(client, webhook_secret, early)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_payment"
    deposit = (await start_deposit(client, user, "10.00")).json()
    early["data"]["id"] = deposit["provider_payment_id"]
    assert (await send_webhook(client, webhook_secret, early)).status_code == 200
    assert await kzt_balance(client, user) == "10.00"


async def test_unsigned_or_forged_webhooks_are_rejected(
    client: AsyncClient, webhook_secret: str
) -> None:
    event = payment_event("pay_1", "succeeded", "10.00")

    unsigned = await client.post("/api/v1/webhooks/payment-provider", json=event)
    forged = await send_webhook(client, "not-the-secret", event)

    assert unsigned.status_code == 400
    assert forged.status_code == 400
    assert forged.json()["error"]["code"] == "invalid_signature"
