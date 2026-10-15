from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid7

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.core.clock import Clock
from payflow.db.models import Account, Transaction, User
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.outbox import OutboxRepository
from payflow.db.repositories.transactions import TransactionRepository
from payflow.db.repositories.users import UserRepository
from payflow.domain.enums import (
    Currency,
    EventType,
    SystemAccount,
    TransactionStatus,
    TransactionType,
)
from payflow.domain.exceptions import (
    AccountNotFoundError,
    RecipientNotFoundError,
    SelfTransferError,
)
from payflow.domain.fraud import (
    FraudAssessment,
    FraudPolicy,
    TransferRisk,
    assess_transfer,
)
from payflow.domain.ledger import move
from payflow.domain.services.ledger import Ledger

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TransferCommand:
    sender_id: UUID
    recipient_phone: str
    amount: Decimal
    currency: Currency
    comment: str | None = None


class TransferService:
    """Moves money between wallets; risky transfers are parked on a review hold."""

    def __init__(
        self, session: AsyncSession, policy: FraudPolicy, clock: Clock
    ) -> None:
        self._session = session
        self._policy = policy
        self._clock = clock
        self._users = UserRepository(session)
        self._accounts = AccountRepository(session)
        self._transactions = TransactionRepository(session)
        self._outbox = OutboxRepository(session)
        self._ledger = Ledger(session)

    async def transfer(self, command: TransferCommand) -> Transaction:
        sender, recipient = await self._parties(command)
        source = await self._wallet(sender, command.currency)
        destination = await self._wallet(recipient, command.currency)
        now = self._clock()
        assessment = assess_transfer(
            TransferRisk(
                amount=command.amount,
                currency=command.currency,
                is_new_recipient=not await self._transactions.has_completed_transfer(
                    sender.id, recipient.id
                ),
                occurred_at=now,
            ),
            self._policy,
        )
        transaction = Transaction(
            id=uuid7(),
            type=TransactionType.TRANSFER,
            status=TransactionStatus.COMPLETED,
            initiator=sender,
            counterparty=recipient,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=command.amount,
            currency=command.currency,
            comment=command.comment,
        )
        self._transactions.add(transaction)
        await self._session.flush()

        if assessment.requires_review:
            await self._hold_for_review(transaction, source, assessment)
        else:
            await self._complete(transaction, source, destination, now)
        return transaction

    async def _parties(self, command: TransferCommand) -> tuple[User, User]:
        sender = await self._users.get(command.sender_id)
        recipient = await self._users.get_by_phone(command.recipient_phone)
        if sender is None:
            raise AccountNotFoundError
        if recipient is None or not recipient.is_active:
            raise RecipientNotFoundError
        if recipient.id == sender.id:
            raise SelfTransferError
        return sender, recipient

    async def _wallet(self, user: User, currency: Currency) -> Account:
        wallet = await self._accounts.get_wallet(user.id, currency)
        if wallet is None:
            raise AccountNotFoundError
        return wallet

    async def _complete(
        self,
        transaction: Transaction,
        source: Account,
        destination: Account,
        completed_at: datetime,
    ) -> None:
        accounts = await self._ledger.lock(source.id, destination.id)
        await self._ledger.post(
            transaction,
            *move(accounts[source.id], accounts[destination.id], transaction.amount),
        )
        transaction.completed_at = completed_at
        self._outbox.publish(EventType.TRANSFER_COMPLETED, transaction)
        logger.info("transfer.completed", transaction_id=str(transaction.id))

    async def _hold_for_review(
        self, transaction: Transaction, source: Account, assessment: FraudAssessment
    ) -> None:
        hold = await self._accounts.system_account(
            SystemAccount.REVIEW_HOLD, transaction.currency
        )
        accounts = await self._ledger.lock(source.id, hold.id)
        await self._ledger.post(
            transaction,
            *move(accounts[source.id], accounts[hold.id], transaction.amount),
        )
        transaction.status = TransactionStatus.PENDING_REVIEW
        transaction.review_reasons = [signal.value for signal in assessment.signals]
        self._outbox.publish(EventType.TRANSFER_HELD, transaction)
        logger.warning(
            "transfer.held_for_review",
            transaction_id=str(transaction.id),
            score=assessment.score,
            signals=transaction.review_reasons,
        )
