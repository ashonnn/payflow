from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Transaction
from payflow.db.repositories.transactions import TransactionRepository
from payflow.domain.exceptions import TransactionNotFoundError


class HistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._transactions = TransactionRepository(session)

    async def get(self, viewer_id: UUID, transaction_id: UUID) -> Transaction:
        transaction = await self._transactions.get_visible(transaction_id, viewer_id)
        if transaction is None:
            raise TransactionNotFoundError
        return transaction
