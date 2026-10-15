from typing import Any

from payflow.db.models import Transaction


def transaction_payload(transaction: Transaction) -> dict[str, Any]:
    return {
        "transaction_id": str(transaction.id),
        "type": transaction.type.value,
        "status": transaction.status.value,
        "initiator_id": str(transaction.initiator_id),
        "counterparty_id": _optional_str(transaction.counterparty_id),
        "amount": str(transaction.amount),
        "currency": transaction.currency.value,
        "counter_amount": _optional_str(transaction.counter_amount),
        "counter_currency": _optional_str(transaction.counter_currency),
        "failure_reason": transaction.failure_reason,
    }


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)
