from enum import StrEnum


class Currency(StrEnum):
    KZT = "KZT"
    USD = "USD"


class TransactionType(StrEnum):
    DEPOSIT = "deposit"
    TRANSFER = "transfer"
    EXCHANGE = "exchange"


class TransactionStatus(StrEnum):
    PENDING = "pending"
    PENDING_REVIEW = "pending_review"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class SystemAccount(StrEnum):
    PROVIDER_CLEARING = "provider_clearing"
    FX_POOL = "fx_pool"
    REVIEW_HOLD = "review_hold"


class EventType(StrEnum):
    DEPOSIT_COMPLETED = "deposit.completed"
    DEPOSIT_FAILED = "deposit.failed"
    TRANSFER_COMPLETED = "transfer.completed"
    TRANSFER_HELD = "transfer.held"
    TRANSFER_REJECTED = "transfer.rejected"
    EXCHANGE_COMPLETED = "exchange.completed"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class ReconciliationStatus(StrEnum):
    OK = "ok"
    MISMATCH = "mismatch"
