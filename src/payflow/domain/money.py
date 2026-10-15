from decimal import ROUND_DOWN, Decimal

CENT = Decimal("0.01")
RATE_STEP = Decimal("0.00000001")


def to_cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT)


def apply_spread(mid_rate: Decimal, spread: Decimal) -> Decimal:
    """Mid rate minus the spread, rounded down so an exchange never creates money."""
    return (mid_rate * (1 - spread)).quantize(RATE_STEP, rounding=ROUND_DOWN)


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    return (amount * rate).quantize(CENT, rounding=ROUND_DOWN)
