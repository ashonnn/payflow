import asyncio
import hashlib
import hmac
import json
import math
import secrets
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

import httpx
import structlog
from pydantic import BaseModel, Field

from mock_provider.config import ProviderSettings

SIGNATURE_HEADER = "X-Provider-Signature"

logger = structlog.get_logger(__name__)


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaymentRequest(BaseModel):
    reference: str = Field(max_length=64)
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: Literal["KZT", "USD"]


class Payment(BaseModel):
    id: str
    reference: str
    amount: Decimal
    currency: str
    status: PaymentStatus = PaymentStatus.PENDING
    failure_reason: str | None = None
    created_at: datetime


def sign(secret: str, payload: bytes, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def payment_event(payment: Payment) -> dict[str, Any]:
    return {
        "id": f"evt_{secrets.token_hex(12)}",
        "type": f"payment.{payment.status}",
        "created": int(time.time()),
        "data": payment.model_dump(mode="json"),
    }


def usd_kzt_rate(settings: ProviderSettings, at: float) -> Decimal:
    """Base rate with a slow sine-wave drift, so successive fetches differ."""
    swing = Decimal(math.sin(2 * math.pi * at / settings.rate_period_seconds))
    rate = settings.usd_kzt_rate * (1 + settings.rate_swing * swing)
    return rate.quantize(Decimal("0.0001"))


class Gateway:
    """In-memory payments that settle after a delay and report back by webhook."""

    def __init__(
        self, settings: ProviderSettings, webhook_client: httpx.AsyncClient
    ) -> None:
        self._settings = settings
        self._client = webhook_client
        self._payments: dict[str, Payment] = {}
        self._by_idempotency_key: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def get(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)

    def create(self, request: PaymentRequest, idempotency_key: str) -> Payment:
        if payment_id := self._by_idempotency_key.get(idempotency_key):
            return self._payments[payment_id]
        payment = Payment(
            id=f"pay_{secrets.token_hex(12)}",
            reference=request.reference,
            amount=request.amount,
            currency=request.currency,
            created_at=datetime.now(UTC),
        )
        self._payments[payment.id] = payment
        self._by_idempotency_key[idempotency_key] = payment.id
        self._spawn(self._capture_later(payment))
        return payment

    async def deliver(self, event: dict[str, Any]) -> bool:
        """POST a signed event with exponential backoff; False if every attempt failed."""
        body = json.dumps(event).encode()
        secret = self._settings.webhook_secret.get_secret_value()
        attempts = self._settings.webhook_max_attempts
        for attempt in range(1, attempts + 1):
            headers = {
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sign(secret, body, int(time.time())),
            }
            try:
                response = await self._client.post(
                    self._settings.webhook_url, content=body, headers=headers
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "webhook.unreachable",
                    event_id=event["id"],
                    attempt=attempt,
                    error=str(exc),
                )
            else:
                if response.is_success:
                    logger.info(
                        "webhook.delivered", event_id=event["id"], attempt=attempt
                    )
                    return True
                logger.warning(
                    "webhook.rejected",
                    event_id=event["id"],
                    attempt=attempt,
                    status=response.status_code,
                )
            if attempt < attempts:
                await asyncio.sleep(
                    self._settings.webhook_retry_base_seconds * 2 ** (attempt - 1)
                )
        logger.error("webhook.abandoned", event_id=event["id"], attempts=attempts)
        return False

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _capture_later(self, payment: Payment) -> None:
        await asyncio.sleep(self._settings.capture_delay_seconds)
        if payment.amount > self._settings.decline_above:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "amount exceeds the card limit"
        else:
            payment.status = PaymentStatus.SUCCEEDED
        await self.deliver(payment_event(payment))

    def _spawn(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
