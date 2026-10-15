from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from payflow.domain.enums import Currency, Direction, TransactionStatus, TransactionType


@dataclass(frozen=True, slots=True)
class HistoryFilter:
    type: TransactionType | None = None
    status: TransactionStatus | None = None
    currency: Currency | None = None
    direction: Direction | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class FeedPosition:
    created_at: datetime
    id: UUID
