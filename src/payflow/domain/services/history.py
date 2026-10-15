from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Transaction
from payflow.db.repositories.transactions import TransactionRepository
from payflow.domain.exceptions import TransactionNotFoundError
from payflow.domain.history import FeedPosition, HistoryFilter


@dataclass(frozen=True, slots=True)
class HistoryPage:
    items: Sequence[Transaction]
    next_position: FeedPosition | None


class HistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._transactions = TransactionRepository(session)

    async def get(self, viewer_id: UUID, transaction_id: UUID) -> Transaction:
        transaction = await self._transactions.get_visible(transaction_id, viewer_id)
        if transaction is None:
            raise TransactionNotFoundError
        return transaction

    async def page(
        self,
        viewer_id: UUID,
        filters: HistoryFilter,
        *,
        after: FeedPosition | None,
        limit: int,
    ) -> HistoryPage:
        """Newest first; `after` continues from the last item of the previous page."""
        rows = await self._transactions.feed(
            viewer_id, filters, after=after, limit=limit + 1
        )
        items = rows[:limit]
        has_more = len(rows) > limit
        next_position = (
            FeedPosition(items[-1].created_at, items[-1].id) if has_more else None
        )
        return HistoryPage(items=items, next_position=next_position)
