import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import Receive, Scope, Send

from mock_provider.config import ProviderSettings
from mock_provider.main import create_app as create_provider_app
from payflow.container import build_container
from payflow.core.config import Settings
from payflow.main import create_app
from tests.integration.helpers import ApiUser, sign_up, start_deposit


@asynccontextmanager
async def wired_apps(settings: Settings) -> AsyncIterator[AsyncClient]:
    """PayFlow and the mock provider, each calling the other in-process."""
    payflow: list[FastAPI] = []

    async def payflow_asgi(scope: Scope, receive: Receive, send: Send) -> None:
        await payflow[0](scope, receive, send)

    provider = create_provider_app(
        ProviderSettings(
            api_key=settings.payment_provider_api_key,
            webhook_url="http://payflow/api/v1/webhooks/payment-provider",
            webhook_secret=settings.payment_provider_webhook_secret,
            capture_delay_seconds=0,
            webhook_retry_base_seconds=0.05,
            decline_above=Decimal(10_000),
            log_json=False,
        ),
        AsyncClient(transport=ASGITransport(app=payflow_asgi)),
    )
    payflow.append(
        create_app(
            build_container(settings, http_transport=ASGITransport(app=provider))
        )
    )
    async with (
        LifespanManager(provider),
        LifespanManager(payflow[0]),
        AsyncClient(
            transport=ASGITransport(app=payflow[0]), base_url="http://payflow"
        ) as client,
    ):
        yield client


async def wait_for_status(
    client: AsyncClient, user: ApiUser, deposit_id: str, expected: str
) -> None:
    async with asyncio.timeout(5):
        while True:
            history = await client.get(
                f"/api/v1/transactions/{deposit_id}", headers=user.headers
            )
            if history.status_code == 200 and history.json()["status"] == expected:
                return
            await asyncio.sleep(0.05)


async def test_deposit_settles_through_mock_provider(
    settings: Settings, engine: AsyncEngine
) -> None:
    async with wired_apps(settings) as client:
        user = await sign_up(client, "+77017770001")

        deposit = (await start_deposit(client, user, "2500.00")).json()
        await wait_for_status(client, user, deposit["id"], "completed")

        accounts = (await client.get("/api/v1/accounts", headers=user.headers)).json()
        assert accounts[0] == accounts[0] | {"currency": "KZT", "balance": "2500.00"}


async def test_declined_payment_fails_deposit(
    settings: Settings, engine: AsyncEngine
) -> None:
    async with wired_apps(settings) as client:
        user = await sign_up(client, "+77017770002")

        deposit = (await start_deposit(client, user, "10000.01")).json()
        await wait_for_status(client, user, deposit["id"], "failed")
