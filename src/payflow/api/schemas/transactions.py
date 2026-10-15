from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from payflow.db.models import Transaction
from payflow.domain.enums import (
    Currency,
    Direction,
    TransactionStatus,
    TransactionType,
)


class TransactionResponse(BaseModel):
    id: UUID
    type: TransactionType
    status: TransactionStatus
    direction: Direction
    amount: Decimal
    currency: Currency
    counter_amount: Decimal | None
    counter_currency: Currency | None
    exchange_rate: Decimal | None
    counterparty_phone: str | None
    comment: str | None
    review_reasons: list[str] | None
    failure_reason: str | None
    provider_payment_id: str | None
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def for_viewer(cls, transaction: Transaction, viewer_id: UUID) -> Self:
        is_initiator = transaction.initiator_id == viewer_id
        return cls(
            id=transaction.id,
            type=transaction.type,
            status=transaction.status,
            direction=transaction.direction_for(viewer_id),
            amount=transaction.amount,
            currency=transaction.currency,
            counter_amount=transaction.counter_amount,
            counter_currency=transaction.counter_currency,
            exchange_rate=transaction.exchange_rate,
            counterparty_phone=transaction.counterparty_phone_for(viewer_id),
            comment=transaction.comment,
            review_reasons=transaction.review_reasons if is_initiator else None,
            failure_reason=transaction.failure_reason,
            provider_payment_id=transaction.external_id if is_initiator else None,
            created_at=transaction.created_at,
            completed_at=transaction.completed_at,
        )
