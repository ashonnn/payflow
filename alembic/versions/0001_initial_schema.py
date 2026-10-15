"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-15 20:06:44
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENCIES = ("KZT", "USD")
EVENT_TYPES = (
    "deposit.completed",
    "deposit.failed",
    "transfer.completed",
    "transfer.held",
    "transfer.rejected",
    "exchange.completed",
)

CREATE_BALANCE_CHECK = """
CREATE FUNCTION ledger_entries_assert_balanced() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ledger_entries
        WHERE transaction_id = NEW.transaction_id
        GROUP BY currency
        HAVING sum(amount) <> 0
    ) THEN
        RAISE EXCEPTION 'ledger entries of transaction % do not balance', NEW.transaction_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$
"""

CREATE_BALANCE_TRIGGER = """
CREATE CONSTRAINT TRIGGER ledger_entries_balanced
AFTER INSERT ON ledger_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION ledger_entries_assert_balanced()
"""

CREATE_APPEND_ONLY_CHECK = """
CREATE FUNCTION ledger_entries_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ledger_entries is append-only';
END;
$$
"""

CREATE_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER ledger_entries_append_only
BEFORE UPDATE OR DELETE ON ledger_entries
FOR EACH ROW EXECUTE FUNCTION ledger_entries_reject_change()
"""


def string_enum(name: str, *values: str, length: int = 32) -> sa.Enum:
    return sa.Enum(
        *values, name=name, native_enum=False, create_constraint=True, length=length
    )


def timestamp_now(name: str) -> sa.Column[datetime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phone", sa.String(16), nullable=False, unique=True),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        timestamp_now("created_at"),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "system_code",
            string_enum("system_code", "provider_clearing", "fx_pool", "review_hold"),
            nullable=True,
        ),
        sa.Column(
            "currency", string_enum("currency", *CURRENCIES, length=3), nullable=False
        ),
        sa.Column(
            "balance", sa.Numeric(18, 2), server_default=sa.text("0"), nullable=False
        ),
        timestamp_now("created_at"),
        sa.UniqueConstraint("user_id", "currency"),
        sa.UniqueConstraint("system_code", "currency"),
        sa.UniqueConstraint("id", "currency"),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (system_code IS NULL)", name="owned_by_user_or_system"
        ),
        sa.CheckConstraint(
            "system_code IS NOT NULL OR balance >= 0", name="user_balance_not_negative"
        ),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "type",
            string_enum("type", "deposit", "transfer", "exchange"),
            nullable=False,
        ),
        sa.Column(
            "status",
            string_enum(
                "status", "pending", "pending_review", "completed", "failed", "rejected"
            ),
            nullable=False,
        ),
        sa.Column("initiator_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("source_account_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
        sa.Column(
            "destination_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency", string_enum("currency", *CURRENCIES, length=3), nullable=False
        ),
        sa.Column("counter_amount", sa.Numeric(18, 2)),
        sa.Column(
            "counter_currency", string_enum("counter_currency", *CURRENCIES, length=3)
        ),
        sa.Column("exchange_rate", sa.Numeric(18, 8)),
        sa.Column("external_id", sa.String(64), unique=True),
        sa.Column("comment", sa.String(140)),
        sa.Column("review_reasons", JSONB()),
        sa.Column("failure_reason", sa.String(255)),
        sa.Column("reviewed_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        timestamp_now("created_at"),
        timestamp_now("updated_at"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
    )
    op.create_index(
        "ix_transactions_initiator_feed",
        "transactions",
        ["initiator_id", "created_at", "id"],
    )
    op.create_index(
        "ix_transactions_counterparty_feed",
        "transactions",
        ["counterparty_id", "created_at", "id"],
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "currency", string_enum("currency", *CURRENCIES, length=3), nullable=False
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        timestamp_now("created_at"),
        sa.ForeignKeyConstraint(
            ["account_id", "currency"], ["accounts.id", "accounts.currency"]
        ),
        sa.CheckConstraint("amount <> 0", name="amount_not_zero"),
    )
    op.create_index(
        "ix_ledger_entries_transaction_id", "ledger_entries", ["transaction_id"]
    )
    op.create_index(
        "ix_ledger_entries_account_id_id", "ledger_entries", ["account_id", "id"]
    )
    op.execute(CREATE_BALANCE_CHECK)
    op.execute(CREATE_BALANCE_TRIGGER)
    op.execute(CREATE_APPEND_ONLY_CHECK)
    op.execute(CREATE_APPEND_ONLY_TRIGGER)

    op.create_table(
        "idempotency_keys",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", JSONB()),
        timestamp_now("created_at"),
    )
    op.create_index(
        "ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"]
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "event_type",
            string_enum("event_type", *EVENT_TYPES, length=64),
            nullable=False,
        ),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "status",
            string_enum("status", "pending", "processed", "failed"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_error", sa.Text()),
        timestamp_now("available_at"),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        timestamp_now("created_at"),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["available_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "event_type",
            string_enum("event_type", *EVENT_TYPES, length=64),
            nullable=False,
        ),
        sa.Column("message", sa.String(255), nullable=False),
        timestamp_now("created_at"),
        sa.UniqueConstraint("event_id", "user_id"),
    )
    op.create_index("ix_notifications_user_id_id", "notifications", ["user_id", "id"])

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        timestamp_now("received_at"),
    )

    op.create_table(
        "reconciliation_reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("status", string_enum("status", "ok", "mismatch"), nullable=False),
        sa.Column("accounts_checked", sa.Integer(), nullable=False),
        sa.Column("issues", JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reconciliation_reports")
    op.drop_table("webhook_events")
    op.drop_table("notifications")
    op.drop_table("outbox_events")
    op.drop_table("idempotency_keys")
    op.drop_table("ledger_entries")
    op.execute("DROP FUNCTION ledger_entries_reject_change()")
    op.execute("DROP FUNCTION ledger_entries_assert_balanced()")
    op.drop_table("transactions")
    op.drop_table("accounts")
    op.drop_table("users")
