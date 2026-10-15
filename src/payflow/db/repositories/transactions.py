from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from payflow.db.models import Transaction
from payflow.domain.enums import TransactionStatus


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
            .options(
                joinedload(Transaction.initiator), joinedload(Transaction.counterparty)
            )
            .where(Transaction.id == transaction_id, visible_to(viewer_id))
        )
        return result.one_or_none()

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
