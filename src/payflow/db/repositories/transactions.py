from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from payflow.db.models import Transaction
from payflow.domain.enums import TransactionStatus, TransactionType

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

    async def lock(self, transaction_id: UUID) -> Transaction | None:
        result = await self._session.scalars(
            select(Transaction)
            .options(*WITH_PARTIES)
            .where(Transaction.id == transaction_id)
            .with_for_update(of=Transaction)
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
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()
