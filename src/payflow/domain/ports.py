from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from payflow.domain.enums import Currency


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProviderPayment:
    id: str
    status: PaymentStatus


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    event_id: str
    event_type: str
    payment_id: str
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    failure_reason: str | None
    payload: dict[str, Any]


class PaymentProvider(Protocol):
    async def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: Currency,
        idempotency_key: str,
    ) -> ProviderPayment: ...
