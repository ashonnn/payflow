from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from payflow.db.models import Transaction
from payflow.domain.enums import Direction, TransactionStatus, TransactionType
from payflow.domain.history import FeedPosition, HistoryFilter

WITH_PARTIES = (joinedload(Transaction.initiator), joinedload(Transaction.counterparty))


def visible_to(viewer_id: UUID) -> ColumnElement[bool]:
    """Initiators see everything they started; recipients see settled transfers."""
    return or_(
        Transaction.initiator_id == viewer_id,
        and_(
            Transaction.counterparty_id == viewer_id,
            Transaction.status == TransactionStatus.COMPLETED,
        ),
    )


def filter_clauses(
    viewer_id: UUID, filters: HistoryFilter
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if filters.type is not None:
        clauses.append(Transaction.type == filters.type)
    if filters.status is not None:
        clauses.append(Transaction.status == filters.status)
    if filters.currency is not None:
        clauses.append(
            or_(
                Transaction.currency == filters.currency,
                Transaction.counter_currency == filters.currency,
            )
        )
    if filters.direction is not None:
        clauses.append(direction_clause(viewer_id, filters.direction))
    if filters.created_from is not None:
        clauses.append(Transaction.created_at >= filters.created_from)
    if filters.created_to is not None:
        clauses.append(Transaction.created_at < filters.created_to)
    if filters.min_amount is not None:
        clauses.append(Transaction.amount >= filters.min_amount)
    if filters.max_amount is not None:
        clauses.append(Transaction.amount <= filters.max_amount)
    return clauses


def direction_clause(viewer_id: UUID, direction: Direction) -> ColumnElement[bool]:
    started_by_viewer = Transaction.initiator_id == viewer_id
    match direction:
        case Direction.INCOMING:
            return or_(
                and_(Transaction.type == TransactionType.DEPOSIT, started_by_viewer),
                and_(
                    Transaction.type == TransactionType.TRANSFER,
                    Transaction.counterparty_id == viewer_id,
                ),
            )
        case Direction.OUTGOING:
            return and_(Transaction.type == TransactionType.TRANSFER, started_by_viewer)
        case Direction.INTERNAL:
            return and_(Transaction.type == TransactionType.EXCHANGE, started_by_viewer)


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, transaction: Transaction) -> None:
        self._session.add(transaction)

    async def get_visible(
        self, transaction_id: UUID, viewer_id: UUID
    ) -> Transaction | None:
        result = await self._session.scalars(
            select(Transaction)
            .options(*WITH_PARTIES)
            .where(Transaction.id == transaction_id, visible_to(viewer_id))
        )
        return result.one_or_none()

    async def feed(
        self,
        viewer_id: UUID,
        filters: HistoryFilter,
        *,
        after: FeedPosition | None,
        limit: int,
    ) -> Sequence[Transaction]:
        statement = (
            select(Transaction)
            .options(*WITH_PARTIES)
            .where(visible_to(viewer_id), *filter_clauses(viewer_id, filters))
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                tuple_(Transaction.created_at, Transaction.id)
                < tuple_(literal(after.created_at), literal(after.id))
            )
        result = await self._session.scalars(statement)
        return result.all()

    async def lock(self, transaction_id: UUID) -> Transaction | None:
        result = await self._session.scalars(
            select(Transaction)
            .options(*WITH_PARTIES)
            .where(Transaction.id == transaction_id)
            .with_for_update(of=Transaction, key_share=True)
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()

    async def has_completed_transfer(self, sender_id: UUID, recipient_id: UUID) -> bool:
        statement = select(
            exists().where(
                Transaction.type == TransactionType.TRANSFER,
                Transaction.initiator_id == sender_id,
                Transaction.counterparty_id == recipient_id,
                Transaction.status == TransactionStatus.COMPLETED,
            )
        )
        return bool(await self._session.scalar(statement))

    async def list_pending_review(self, limit: int) -> Sequence[Transaction]:
        result = await self._session.scalars(
            select(Transaction)
            .options(*WITH_PARTIES)
            .where(Transaction.status == TransactionStatus.PENDING_REVIEW)
            .order_by(Transaction.created_at, Transaction.id)
            .limit(limit)
        )
        return result.all()

    async def get_by_external_id(self, external_id: str) -> Transaction | None:
        result = await self._session.scalars(
            select(Transaction).where(Transaction.external_id == external_id)
        )
        return result.one_or_none()

    async def lock_by_external_id(self, external_id: str) -> Transaction | None:
        result = await self._session.scalars(
            select(Transaction)
            .where(Transaction.external_id == external_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()
