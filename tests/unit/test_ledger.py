from decimal import Decimal
from uuid import uuid7

import pytest

from payflow.db.models import Account
from payflow.domain.enums import Currency, SystemAccount
from payflow.domain.ledger import Posting, ensure_balanced, move


def wallet(currency: Currency = Currency.KZT) -> Account:
    return Account(id=uuid7(), user_id=uuid7(), currency=currency)


def system(currency: Currency) -> Account:
    return Account(id=uuid7(), system_code=SystemAccount.FX_POOL, currency=currency)


def test_move_debits_source_and_credits_destination() -> None:
    source, destination = wallet(), wallet()

    debit, credit = move(source, destination, Decimal("25.50"))

    assert debit == Posting(source.id, Currency.KZT, Decimal("-25.50"))
    assert credit == Posting(destination.id, Currency.KZT, Decimal("25.50"))
    ensure_balanced([debit, credit])


def test_move_cannot_change_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        move(wallet(Currency.KZT), wallet(Currency.USD), Decimal(1))


@pytest.mark.parametrize("amount", [Decimal(0), Decimal("-0.01")])
def test_move_needs_positive_amount(amount: Decimal) -> None:
    with pytest.raises(ValueError, match="positive"):
        move(wallet(), wallet(), amount)


def test_exchange_balances_per_currency() -> None:
    postings = [
        *move(wallet(Currency.USD), system(Currency.USD), Decimal(10)),
        *move(system(Currency.KZT), wallet(Currency.KZT), Decimal(5050)),
    ]

    ensure_balanced(postings)


def test_unbalanced_postings_are_rejected() -> None:
    account = wallet()
    postings = [
        Posting(account.id, Currency.KZT, Decimal(10)),
        Posting(account.id, Currency.USD, Decimal(-10)),
    ]

    with pytest.raises(ValueError, match="KZT, USD"):
        ensure_balanced(postings)


def test_zero_and_empty_postings_are_rejected() -> None:
    with pytest.raises(ValueError, match="zero"):
        ensure_balanced([Posting(uuid7(), Currency.KZT, Decimal(0))])
    with pytest.raises(ValueError, match="at least one"):
        ensure_balanced([])
