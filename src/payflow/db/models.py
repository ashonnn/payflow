from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid7

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from payflow.db.base import Base, str_enum
from payflow.domain.enums import (
    Currency,
    EventType,
    OutboxStatus,
    ReconciliationStatus,
    SystemAccount,
    TransactionStatus,
    TransactionType,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    phone: Mapped[str] = mapped_column(String(16), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    is_admin: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __str__(self) -> str:
        return self.phone


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "currency"),
        UniqueConstraint("system_code", "currency"),
        UniqueConstraint("id", "currency"),
        CheckConstraint(
            "(user_id IS NULL) <> (system_code IS NULL)", name="owned_by_user_or_system"
        ),
        CheckConstraint(
            "system_code IS NOT NULL OR balance >= 0", name="user_balance_not_negative"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    system_code: Mapped[SystemAccount | None] = mapped_column(
        str_enum(SystemAccount, "system_code")
    )
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency", length=3))
    balance: Mapped[Decimal] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User | None] = relationship(lazy="raise")

    @property
    def is_system(self) -> bool:
        return self.system_code is not None

    def __str__(self) -> str:
        owner = self.system_code or self.user_id
        return f"{owner} {self.currency}"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_transactions_initiator_feed", "initiator_id", "created_at", "id"),
        Index(
            "ix_transactions_counterparty_feed", "counterparty_id", "created_at", "id"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    type: Mapped[TransactionType] = mapped_column(str_enum(TransactionType, "type"))
    status: Mapped[TransactionStatus] = mapped_column(
        str_enum(TransactionStatus, "status")
    )
    initiator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    counterparty_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    source_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))
    destination_account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal]
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency", length=3))
    counter_amount: Mapped[Decimal | None]
    counter_currency: Mapped[Currency | None] = mapped_column(
        str_enum(Currency, "counter_currency", length=3)
    )
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    comment: Mapped[str | None] = mapped_column(String(140))
    review_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None]

    initiator: Mapped[User] = relationship(foreign_keys=[initiator_id], lazy="raise")
    counterparty: Mapped[User | None] = relationship(
        foreign_keys=[counterparty_id], lazy="raise"
    )

    def __str__(self) -> str:
        return f"{self.type} {self.amount} {self.currency} ({self.status})"


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        # composite key keeps an entry's currency equal to its account's currency
        ForeignKeyConstraint(
            ["account_id", "currency"], ["accounts.id", "accounts.currency"]
        ),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        Index("ix_ledger_entries_account_id_id", "account_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id"), index=True
    )
    account_id: Mapped[UUID]
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency", length=3))
    amount: Mapped[Decimal]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    account: Mapped[Account] = relationship(lazy="raise")
    transaction: Mapped[Transaction] = relationship(lazy="raise")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_pending",
            "available_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_type: Mapped[EventType] = mapped_column(
        str_enum(EventType, "event_type", length=64)
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[OutboxStatus] = mapped_column(
        str_enum(OutboxStatus, "status"), server_default=OutboxStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        Index("ix_notifications_user_id_id", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    event_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[EventType] = mapped_column(
        str_enum(EventType, "event_type", length=64)
    )
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    status: Mapped[ReconciliationStatus] = mapped_column(
        str_enum(ReconciliationStatus, "status")
    )
    accounts_checked: Mapped[int]
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]
