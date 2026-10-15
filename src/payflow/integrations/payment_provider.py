import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import httpx
from pydantic import BaseModel, ValidationError

from payflow.core.clock import Clock
from payflow.domain.enums import Currency
from payflow.domain.exceptions import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    PaymentProviderUnavailableError,
)
from payflow.domain.ports import PaymentEvent, PaymentStatus, ProviderPayment

SIGNATURE_HEADER = "X-Provider-Signature"


class _PaymentResponse(BaseModel):
    id: str
    status: PaymentStatus


class _WebhookPayment(BaseModel):
    id: str
    amount: Decimal
    currency: Currency
    status: PaymentStatus
    failure_reason: str | None = None


class _WebhookEnvelope(BaseModel):
    id: str
    type: str
    data: _WebhookPayment


class HttpPaymentProvider:
    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    async def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: Currency,
        idempotency_key: str,
    ) -> ProviderPayment:
        try:
            response = await self._client.post(
                "/v1/payments",
                json={
                    "reference": reference,
                    "amount": str(amount),
                    "currency": currency,
                },
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Idempotency-Key": idempotency_key,
                },
            )
            response.raise_for_status()
            payment = _PaymentResponse.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise PaymentProviderUnavailableError from exc
        return ProviderPayment(id=payment.id, status=payment.status)


class WebhookVerifier:
    """Checks `t=<unix ts>,v1=<hex hmac-sha256 of "ts.body">` signature headers."""

    def __init__(self, secret: str, tolerance: timedelta, clock: Clock) -> None:
        self._secret = secret.encode()
        self._tolerance = tolerance
        self._clock = clock

    def verify(self, payload: bytes, header: str | None) -> None:
        if not header:
            raise InvalidWebhookSignatureError
        fields: dict[str, str] = {}
        for part in header.split(","):
            name, _, value = part.strip().partition("=")
            fields[name] = value
        try:
            timestamp = int(fields["t"])
            signature = fields["v1"]
        except (KeyError, ValueError) as exc:
            raise InvalidWebhookSignatureError from exc
        age = abs(self._clock().timestamp() - timestamp)
        if age > self._tolerance.total_seconds():
            raise InvalidWebhookSignatureError("webhook signature has expired")
        signed = f"{timestamp}.".encode() + payload
        expected = hmac.new(self._secret, signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidWebhookSignatureError


def parse_payment_event(payload: bytes) -> PaymentEvent:
    try:
        envelope = _WebhookEnvelope.model_validate_json(payload)
    except ValidationError as exc:
        raise InvalidWebhookPayloadError from exc
    payment = envelope.data
    return PaymentEvent(
        event_id=envelope.id,
        event_type=envelope.type,
        payment_id=payment.id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        failure_reason=payment.failure_reason,
        payload=json.loads(payload),
    )
