from datetime import UTC, datetime
from decimal import Decimal

import pytest

from payflow.domain.enums import Currency
from payflow.domain.exceptions import RatesUnavailableError
from payflow.domain.money import apply_spread, convert, to_cents
from payflow.domain.ports import RateSnapshot

SNAPSHOT = RateSnapshot(
    usd_rates={Currency.USD: Decimal(1), Currency.KZT: Decimal("505.25")},
    fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
)


def test_amounts_are_kept_to_cents() -> None:
    assert to_cents(Decimal(15)) == Decimal("15.00")
    assert str(to_cents(Decimal("15.5"))) == "15.50"


def test_spread_is_taken_from_mid_and_rounded_down() -> None:
    assert apply_spread(Decimal(500), Decimal("0.005")) == Decimal("497.50000000")
    assert apply_spread(Decimal("0.00197923"), Decimal("0.005")) == Decimal(
        "0.00196933"
    )


def test_conversion_never_rounds_up() -> None:
    assert convert(Decimal("10.00"), Decimal("0.00199999")) == Decimal("0.01")
    assert convert(Decimal("0.01"), Decimal("0.00199")) == Decimal("0.00")
    assert convert(Decimal("100.00"), Decimal("497.5")) == Decimal("49750.00")


def test_rates_are_crossed_through_usd() -> None:
    assert SNAPSHOT.mid_rate(Currency.USD, Currency.KZT) == Decimal("505.25")
    assert SNAPSHOT.mid_rate(Currency.KZT, Currency.USD) == Decimal(1) / Decimal(
        "505.25"
    )
    assert SNAPSHOT.mid_rate(Currency.KZT, Currency.KZT) == 1


def test_missing_rate_is_reported() -> None:
    partial = RateSnapshot({Currency.USD: Decimal(1)}, SNAPSHOT.fetched_at)

    with pytest.raises(RatesUnavailableError, match="KZT"):
        partial.mid_rate(Currency.USD, Currency.KZT)
