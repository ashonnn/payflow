from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from payflow.core.config import FraudSettings
from payflow.domain.enums import Currency
from payflow.domain.fraud import FraudPolicy, FraudSignal, TransferRisk, assess_transfer

POLICY = FraudPolicy.from_settings(FraudSettings())
# Asia/Almaty is UTC+5
NOON = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
NIGHT = datetime(2026, 10, 14, 21, 30, tzinfo=UTC)


def risk(
    amount: str = "1000",
    currency: Currency = Currency.KZT,
    *,
    new_recipient: bool = False,
    at: datetime = NOON,
) -> TransferRisk:
    return TransferRisk(
        amount=Decimal(amount),
        currency=currency,
        is_new_recipient=new_recipient,
        occurred_at=at,
    )


def test_ordinary_transfer_passes() -> None:
    assessment = assess_transfer(risk(), POLICY)

    assert assessment.score == 0
    assert assessment.signals == ()
    assert not assessment.requires_review


@pytest.mark.parametrize(
    ("amount", "currency", "flagged"),
    [
        ("999999.99", Currency.KZT, False),
        ("1000000", Currency.KZT, True),
        ("1999.99", Currency.USD, False),
        ("2000", Currency.USD, True),
    ],
)
def test_large_amount_alone_requires_review(
    amount: str, currency: Currency, flagged: bool
) -> None:
    assessment = assess_transfer(risk(amount, currency), POLICY)

    assert assessment.requires_review is flagged
    assert (FraudSignal.LARGE_AMOUNT in assessment.signals) is flagged


def test_new_recipient_or_night_alone_pass() -> None:
    assert not assess_transfer(risk(new_recipient=True), POLICY).requires_review
    assert not assess_transfer(risk(at=NIGHT), POLICY).requires_review


def test_new_recipient_at_night_requires_review() -> None:
    assessment = assess_transfer(risk(new_recipient=True, at=NIGHT), POLICY)

    assert assessment.requires_review
    assert assessment.signals == (FraudSignal.NEW_RECIPIENT, FraudSignal.NIGHT_TIME)
    assert assessment.score == 70


@pytest.mark.parametrize(
    ("moment", "is_night"),
    [
        (datetime(2026, 10, 14, 19, 0, tzinfo=UTC), True),
        (datetime(2026, 10, 15, 0, 59, tzinfo=UTC), True),
        (datetime(2026, 10, 15, 1, 0, tzinfo=UTC), False),
        (datetime(2026, 10, 14, 18, 59, tzinfo=UTC), False),
    ],
)
def test_night_is_measured_in_policy_timezone(moment: datetime, is_night: bool) -> None:
    assert POLICY.is_night(moment) is is_night


def test_night_window_can_wrap_midnight() -> None:
    late_evening = replace(POLICY, night_starts_at=time(22), night_ends_at=time(6))

    assert late_evening.is_night(datetime(2026, 10, 15, 18, 0, tzinfo=UTC))
    assert not late_evening.is_night(datetime(2026, 10, 15, 16, 0, tzinfo=UTC))
