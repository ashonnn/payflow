import hmac
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from mock_provider.config import ProviderSettings
from mock_provider.gateway import Gateway, Payment, PaymentRequest, usd_kzt_rate
from payflow.core.logging import configure_logging


class RatesResponse(BaseModel):
    base: str
    rates: dict[str, Decimal]
    timestamp: datetime


def create_app(
    settings: ProviderSettings | None = None,
    webhook_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    settings = settings or ProviderSettings()
    configure_logging(settings.log_level, json=settings.log_json)
    client = webhook_client or httpx.AsyncClient(
        timeout=settings.webhook_timeout_seconds
    )
    gateway = Gateway(settings, client)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await gateway.aclose()
        await client.aclose()

    app = FastAPI(title="Mock payment provider", lifespan=lifespan)
    app.state.gateway = gateway
    expected_authorization = f"Bearer {settings.api_key.get_secret_value()}"

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if authorization is None or not hmac.compare_digest(
            authorization, expected_authorization
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")

    @app.post(
        "/v1/payments",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(authorize)],
    )
    async def create_payment(
        request: PaymentRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Payment:
        return gateway.create(request, idempotency_key)

    @app.get("/v1/payments/{payment_id}", dependencies=[Depends(authorize)])
    async def get_payment(payment_id: str) -> Payment:
        if payment := gateway.get(payment_id):
            return payment
        raise HTTPException(status.HTTP_404_NOT_FOUND, "payment not found")

    @app.get("/v1/rates")
    async def rates() -> RatesResponse:
        return RatesResponse(
            base="USD",
            rates={"KZT": usd_kzt_rate(settings, time.time())},
            timestamp=datetime.now(UTC),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
