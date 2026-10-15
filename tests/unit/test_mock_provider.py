import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from mock_provider.config import ProviderSettings
from mock_provider.gateway import SIGNATURE_HEADER, Gateway, usd_kzt_rate
from mock_provider.main import create_app
from payflow.core.clock import utc_now
from payflow.integrations.payment_provider import WebhookVerifier

API_KEY = "provider-key"
WEBHOOK_SECRET = "webhook-secret"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


def provider_settings(**overrides: Any) -> ProviderSettings:
    defaults: dict[str, Any] = {
        "api_key": SecretStr(API_KEY),
        "webhook_url": "http://payflow/webhooks",
        "webhook_secret": SecretStr(WEBHOOK_SECRET),
        "capture_delay_seconds": 0,
        "webhook_retry_base_seconds": 0,
        "log_json": False,
    }
    return ProviderSettings(**(defaults | overrides))


class WebhookReceiver:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.accepted = asyncio.Event()
        self._statuses = iter(statuses or [])

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code = next(self._statuses, 200)
        if status_code == 200:
            self.accepted.set()
        return httpx.Response(status_code)

    def event(self, index: int = -1) -> dict[str, Any]:
        event: dict[str, Any] = json.loads(self.requests[index].content)
        return event


@pytest.fixture
def receiver() -> WebhookReceiver:
    return WebhookReceiver()


@asynccontextmanager
async def provider_client(
    settings: ProviderSettings, receiver: WebhookReceiver
) -> AsyncIterator[httpx.AsyncClient]:
    webhooks = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    app = create_app(settings, webhooks)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://provider"
        ) as client,
    ):
        yield client


@pytest.fixture
async def client(receiver: WebhookReceiver) -> AsyncIterator[httpx.AsyncClient]:
    async with provider_client(provider_settings(), receiver) as client:
        yield client


async def create_payment(
    client: httpx.AsyncClient, amount: str = "100.00", key: str = "key-1"
) -> httpx.Response:
    return await client.post(
        "/v1/payments",
        json={"reference": "ref-1", "amount": amount, "currency": "KZT"},
        headers={**AUTH, "Idempotency-Key": key},
    )


async def test_payments_require_api_key(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/payments",
        json={"reference": "ref", "amount": "1.00", "currency": "KZT"},
        headers={"Authorization": "Bearer wrong", "Idempotency-Key": "k"},
    )

    assert response.status_code == 401


async def test_create_is_idempotent(client: httpx.AsyncClient) -> None:
    first = await create_payment(client)
    second = await create_payment(client)
    other = await create_payment(client, key="key-2")

    assert first.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert other.json()["id"] != first.json()["id"]


async def test_capture_is_reported_with_a_verifiable_signature(
    client: httpx.AsyncClient, receiver: WebhookReceiver
) -> None:
    payment = (await create_payment(client)).json()

    await asyncio.wait_for(receiver.accepted.wait(), timeout=5)

    request = receiver.requests[0]
    verifier = WebhookVerifier(WEBHOOK_SECRET, timedelta(minutes=5), utc_now)
    verifier.verify(request.content, request.headers[SIGNATURE_HEADER])
    event = receiver.event()
    assert event["type"] == "payment.succeeded"
    assert event["data"]["id"] == payment["id"]
    fetched = await client.get(f"/v1/payments/{payment['id']}", headers=AUTH)
    assert fetched.json()["status"] == "succeeded"


async def test_payment_above_limit_is_declined(receiver: WebhookReceiver) -> None:
    async with provider_client(
        provider_settings(decline_above=Decimal(50)), receiver
    ) as client:
        await create_payment(client, amount="50.01")
        await asyncio.wait_for(receiver.accepted.wait(), timeout=5)

    event = receiver.event()
    assert event["type"] == "payment.failed"
    assert event["data"]["failure_reason"] == "amount exceeds the card limit"


async def test_rejected_delivery_is_retried() -> None:
    receiver = WebhookReceiver(statuses=[500, 503, 200])
    async with provider_client(provider_settings(), receiver) as client:
        await create_payment(client)
        await asyncio.wait_for(receiver.accepted.wait(), timeout=5)

    assert len(receiver.requests) == 3
    assert {r.content for r in receiver.requests} == {receiver.requests[0].content}


async def test_delivery_is_abandoned_after_max_attempts() -> None:
    receiver = WebhookReceiver(statuses=[500] * 10)
    webhooks = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    gateway = Gateway(provider_settings(webhook_max_attempts=3), webhooks)

    delivered = await gateway.deliver({"id": "evt_1"})

    assert not delivered
    assert len(receiver.requests) == 3


async def test_unknown_payment_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/payments/pay_missing", headers=AUTH)

    assert response.status_code == 404


async def test_rates_drift_around_base_rate(client: httpx.AsyncClient) -> None:
    settings = provider_settings()
    response = await client.get("/v1/rates")

    rate = Decimal(response.json()["rates"]["KZT"])
    assert response.json()["base"] == "USD"
    assert (
        abs(rate - settings.usd_kzt_rate) <= settings.usd_kzt_rate * settings.rate_swing
    )
    quarter_period = settings.rate_period_seconds / 4
    assert usd_kzt_rate(settings, 0) != usd_kzt_rate(settings, quarter_period)


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.json() == {"status": "ok"}
