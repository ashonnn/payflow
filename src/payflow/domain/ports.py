from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from payflow.domain.enums import Currency
from payflow.domain.exceptions import RatesUnavailableError


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


@dataclass(frozen=True, slots=True)
class RateSnapshot:
    usd_rates: Mapping[Currency, Decimal]
    fetched_at: datetime

    def mid_rate(self, source: Currency, target: Currency) -> Decimal:
        """Units of target per one unit of source, crossed through USD."""
        try:
            return self.usd_rates[target] / self.usd_rates[source]
        except KeyError as exc:
            raise RatesUnavailableError(f"no rate for {exc.args[0]}") from exc


class RatesProvider(Protocol):
    async def usd_rates(self) -> Mapping[Currency, Decimal]: ...


class ExchangeRates(Protocol):
    async def snapshot(self) -> RateSnapshot: ...
