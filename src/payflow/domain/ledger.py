from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from payflow.db.models import Account
from payflow.domain.enums import Currency


@dataclass(frozen=True, slots=True)
class Posting:
    account_id: UUID
    currency: Currency
    amount: Decimal


def move(
    source: Account, destination: Account, amount: Decimal
) -> tuple[Posting, Posting]:
    """Postings that take `amount` from source and give it to destination."""
    if source.currency != destination.currency:
        raise ValueError("a move cannot change currency")
    if amount <= 0:
        raise ValueError("a move needs a positive amount")
    return (
        Posting(source.id, source.currency, -amount),
        Posting(destination.id, destination.currency, amount),
    )


def ensure_balanced(postings: Iterable[Posting]) -> None:
    totals: defaultdict[Currency, Decimal] = defaultdict(Decimal)
    for posting in postings:
        if posting.amount == 0:
            raise ValueError("ledger postings cannot be zero")
        totals[posting.currency] += posting.amount
    if not totals:
        raise ValueError("a ledger posting needs at least one line")
    if unbalanced := sorted(currency for currency, total in totals.items() if total):
        raise ValueError(f"postings do not balance for {', '.join(unbalanced)}")
