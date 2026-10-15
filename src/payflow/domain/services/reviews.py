from collections.abc import Sequence
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.core.clock import Clock
from payflow.db.models import Transaction
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.outbox import OutboxRepository
from payflow.db.repositories.transactions import TransactionRepository
from payflow.domain.enums import (
    EventType,
    SystemAccount,
    TransactionStatus,
    TransactionType,
)
from payflow.domain.exceptions import (
    TransactionNotFoundError,
    TransactionNotReviewableError,
)
from payflow.domain.ledger import move
from payflow.domain.services.ledger import Ledger

logger = structlog.get_logger(__name__)


class ReviewService:
    """Releases held transfers to the recipient or returns them to the sender."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._clock = clock
        self._accounts = AccountRepository(session)
        self._transactions = TransactionRepository(session)
        self._outbox = OutboxRepository(session)
        self._ledger = Ledger(session)

    async def pending(self, limit: int) -> Sequence[Transaction]:
        return await self._transactions.list_pending_review(limit)

    async def approve(self, transaction_id: UUID, reviewer_id: UUID) -> Transaction:
        transaction = await self._held_transfer(transaction_id)
        await self._release_hold(transaction, transaction.destination_account_id)
        transaction.status = TransactionStatus.COMPLETED
        transaction.completed_at = self._clock()
        transaction.reviewed_by_id = reviewer_id
        self._outbox.publish(EventType.TRANSFER_COMPLETED, transaction)
        logger.info(
            "transfer.approved",
            transaction_id=str(transaction.id),
            reviewer_id=str(reviewer_id),
        )
        return transaction

    async def reject(
        self, transaction_id: UUID, reviewer_id: UUID, reason: str
    ) -> Transaction:
        transaction = await self._held_transfer(transaction_id)
        if transaction.source_account_id is None:
            raise TransactionNotReviewableError
        await self._release_hold(transaction, transaction.source_account_id)
        transaction.status = TransactionStatus.REJECTED
        transaction.failure_reason = reason
        transaction.reviewed_by_id = reviewer_id
        self._outbox.publish(EventType.TRANSFER_REJECTED, transaction)
        logger.info(
            "transfer.rejected",
            transaction_id=str(transaction.id),
            reviewer_id=str(reviewer_id),
        )
        return transaction

    async def _held_transfer(self, transaction_id: UUID) -> Transaction:
        transaction = await self._transactions.lock(transaction_id)
        if transaction is None or transaction.type is not TransactionType.TRANSFER:
            raise TransactionNotFoundError
        if transaction.status is not TransactionStatus.PENDING_REVIEW:
            raise TransactionNotReviewableError
        return transaction

    async def _release_hold(self, transaction: Transaction, account_id: UUID) -> None:
        hold = await self._accounts.system_account(
            SystemAccount.REVIEW_HOLD, transaction.currency
        )
        accounts = await self._ledger.lock(hold.id, account_id)
        await self._ledger.post(
            transaction,
            *move(accounts[hold.id], accounts[account_id], transaction.amount),
        )
