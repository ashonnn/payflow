import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mock_provider.gateway import sign
from payflow.domain.enums import Currency
from payflow.domain.exceptions import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
)
from payflow.domain.ports import PaymentStatus
from payflow.integrations.payment_provider import WebhookVerifier, parse_payment_event

SECRET = "webhook-secret"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
BODY = json.dumps(
    {
        "id": "evt_1",
        "type": "payment.succeeded",
        "data": {
            "id": "pay_1",
            "reference": "ref",
            "amount": "1500.00",
            "currency": "KZT",
            "status": "succeeded",
        },
    }
).encode()


@pytest.fixture
def verifier() -> WebhookVerifier:
    return WebhookVerifier(SECRET, timedelta(minutes=5), lambda: NOW)


def signed_at(moment: datetime, body: bytes = BODY, secret: str = SECRET) -> str:
    return sign(secret, body, int(moment.timestamp()))


def test_valid_signature_is_accepted(verifier: WebhookVerifier) -> None:
    verifier.verify(BODY, signed_at(NOW - timedelta(minutes=4)))


def test_tampered_body_is_rejected(verifier: WebhookVerifier) -> None:
    tampered = BODY.replace(b"1500.00", b"9500.00")

    with pytest.raises(InvalidWebhookSignatureError):
        verifier.verify(tampered, signed_at(NOW))


def test_signature_with_other_secret_is_rejected(verifier: WebhookVerifier) -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        verifier.verify(BODY, signed_at(NOW, secret="other-secret"))


def test_replayed_old_signature_is_rejected(verifier: WebhookVerifier) -> None:
    with pytest.raises(InvalidWebhookSignatureError, match="expired"):
        verifier.verify(BODY, signed_at(NOW - timedelta(minutes=6)))


@pytest.mark.parametrize("header", [None, "", "garbage", "t=soon,v1=abc", "v1=abc"])
def test_malformed_header_is_rejected(
    verifier: WebhookVerifier, header: str | None
) -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        verifier.verify(BODY, header)


def test_event_is_parsed_into_payment_fields() -> None:
    event = parse_payment_event(BODY)

    assert event.event_id == "evt_1"
    assert event.payment_id == "pay_1"
    assert event.status is PaymentStatus.SUCCEEDED
    assert (event.amount, event.currency) == (Decimal("1500.00"), Currency.KZT)
    assert event.payload["type"] == "payment.succeeded"


def test_malformed_event_is_rejected() -> None:
    with pytest.raises(InvalidWebhookPayloadError):
        parse_payment_event(b'{"id": "evt_1"}')
