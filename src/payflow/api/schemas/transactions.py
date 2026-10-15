from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from payflow.db.models import Transaction
from payflow.domain.enums import (
    Currency,
    Direction,
    TransactionStatus,
    TransactionType,
)
from payflow.domain.history import HistoryFilter


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TransactionType | None = None
    status: TransactionStatus | None = None
    currency: Currency | None = None
    direction: Direction | None = None
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from >= self.created_to
        ):
            raise ValueError("created_from must be earlier than created_to")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot exceed max_amount")
        return self

    def to_filter(self) -> HistoryFilter:
        return HistoryFilter(
            type=self.type,
            status=self.status,
            currency=self.currency,
            direction=self.direction,
            created_from=self.created_from,
            created_to=self.created_to,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
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


class TransactionPage(BaseModel):
    items: list[TransactionResponse]
    next_cursor: str | None
