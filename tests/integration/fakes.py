import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from payflow.domain.enums import Currency
from payflow.domain.exceptions import (
    PaymentProviderUnavailableError,
    RatesUnavailableError,
)
from payflow.domain.ports import PaymentStatus, ProviderPayment


@dataclass(frozen=True, slots=True)
class PaymentCall:
    reference: str
    amount: Decimal
    currency: Currency
    idempotency_key: str


@dataclass(slots=True)
class FakePaymentProvider:
    calls: list[PaymentCall] = field(default_factory=list)
    available: bool = True

    async def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: Currency,
        idempotency_key: str,
    ) -> ProviderPayment:
        if not self.available:
            raise PaymentProviderUnavailableError
        self.calls.append(PaymentCall(reference, amount, currency, idempotency_key))
        payment_id = "pay_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        return ProviderPayment(id=payment_id, status=PaymentStatus.PENDING)


@dataclass(slots=True)
class FakeRatesProvider:
    usd_kzt: Decimal = Decimal("500.00")
    calls: int = 0
    available: bool = True

    async def usd_rates(self) -> Mapping[Currency, Decimal]:
        if not self.available:
            raise RatesUnavailableError
        self.calls += 1
        return {Currency.USD: Decimal(1), Currency.KZT: self.usd_kzt}
