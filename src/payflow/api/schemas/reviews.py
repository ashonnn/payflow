from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from payflow.db.models import Transaction
from payflow.domain.enums import Currency, TransactionStatus


class ReviewResponse(BaseModel):
    id: UUID
    status: TransactionStatus
    amount: Decimal
    currency: Currency
    sender_phone: str
    recipient_phone: str | None
    review_reasons: list[str]
    comment: str | None
    failure_reason: str | None
    created_at: datetime

    @classmethod
    def from_transaction(cls, transaction: Transaction) -> Self:
        return cls(
            id=transaction.id,
            status=transaction.status,
            amount=transaction.amount,
            currency=transaction.currency,
            sender_phone=transaction.initiator.phone,
            recipient_phone=(
                transaction.counterparty.phone if transaction.counterparty else None
            ),
            review_reasons=transaction.review_reasons or [],
            comment=transaction.comment,
            failure_reason=transaction.failure_reason,
            created_at=transaction.created_at,
        )


class RejectRequest(BaseModel):
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)
    ]
