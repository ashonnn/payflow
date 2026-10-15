from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo

from payflow.core.config import FraudSettings
from payflow.domain.enums import Currency


class FraudSignal(StrEnum):
    LARGE_AMOUNT = "large_amount"
    NEW_RECIPIENT = "new_recipient"
    NIGHT_TIME = "night_time"


@dataclass(frozen=True, slots=True)
class TransferRisk:
    amount: Decimal
    currency: Currency
    is_new_recipient: bool
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class FraudPolicy:
    large_amounts: Mapping[Currency, Decimal]
    night_starts_at: time
    night_ends_at: time
    timezone: ZoneInfo
    weights: Mapping[FraudSignal, int]
    review_threshold: int

    @classmethod
    def from_settings(cls, settings: FraudSettings) -> Self:
        return cls(
            large_amounts={
                Currency.KZT: settings.large_amount_kzt,
                Currency.USD: settings.large_amount_usd,
            },
            night_starts_at=settings.night_starts_at,
            night_ends_at=settings.night_ends_at,
            timezone=ZoneInfo(settings.timezone),
            weights={
                FraudSignal.LARGE_AMOUNT: settings.large_amount_score,
                FraudSignal.NEW_RECIPIENT: settings.new_recipient_score,
                FraudSignal.NIGHT_TIME: settings.night_time_score,
            },
            review_threshold=settings.review_threshold,
        )

    def is_night(self, moment: datetime) -> bool:
        local = moment.astimezone(self.timezone).time()
        if self.night_starts_at <= self.night_ends_at:
            return self.night_starts_at <= local < self.night_ends_at
        return local >= self.night_starts_at or local < self.night_ends_at


@dataclass(frozen=True, slots=True)
class FraudAssessment:
    score: int
    signals: tuple[FraudSignal, ...]
    requires_review: bool


type Rule = Callable[[TransferRisk, FraudPolicy], bool]


def _large_amount(transfer: TransferRisk, policy: FraudPolicy) -> bool:
    return transfer.amount >= policy.large_amounts[transfer.currency]


def _new_recipient(transfer: TransferRisk, _: FraudPolicy) -> bool:
    return transfer.is_new_recipient


def _night_time(transfer: TransferRisk, policy: FraudPolicy) -> bool:
    return policy.is_night(transfer.occurred_at)


RULES: Mapping[FraudSignal, Rule] = {
    FraudSignal.LARGE_AMOUNT: _large_amount,
    FraudSignal.NEW_RECIPIENT: _new_recipient,
    FraudSignal.NIGHT_TIME: _night_time,
}


def assess_transfer(transfer: TransferRisk, policy: FraudPolicy) -> FraudAssessment:
    """Score a transfer; at or above the policy threshold it waits for manual review."""
    signals = tuple(signal for signal, rule in RULES.items() if rule(transfer, policy))
    score = sum(policy.weights[signal] for signal in signals)
    return FraudAssessment(
        score=score, signals=signals, requires_review=score >= policy.review_threshold
    )
