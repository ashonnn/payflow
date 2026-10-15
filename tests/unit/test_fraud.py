from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from payflow.core.config import FraudSettings
from payflow.domain.enums import Currency
from payflow.domain.fraud import FraudPolicy, FraudSignal, TransferRisk, assess_transfer

POLICY = FraudPolicy.from_settings(FraudSettings())
ALMATY = ZoneInfo("Asia/Almaty")
NOON = datetime(2026, 10, 15, 12, 0, tzinfo=ALMATY)
NIGHT = datetime(2026, 10, 15, 2, 30, tzinfo=ALMATY)


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
    ("local_time", "is_night"),
    [
        (time(0, 0), True),
        (time(5, 59), True),
        (time(6, 0), False),
        (time(23, 59), False),
    ],
)
def test_night_is_measured_in_policy_timezone(local_time: time, is_night: bool) -> None:
    moment = datetime.combine(NOON.date(), local_time, tzinfo=ALMATY).astimezone(UTC)

    assert POLICY.is_night(moment) is is_night


def test_night_window_can_wrap_midnight() -> None:
    late_evening = replace(POLICY, night_starts_at=time(22), night_ends_at=time(6))

    assert late_evening.is_night(datetime(2026, 10, 15, 23, 0, tzinfo=ALMATY))
    assert not late_evening.is_night(datetime(2026, 10, 15, 21, 0, tzinfo=ALMATY))
