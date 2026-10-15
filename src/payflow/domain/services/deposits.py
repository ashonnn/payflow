import hashlib
from decimal import Decimal
from uuid import UUID, uuid7

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.core.clock import Clock
from payflow.db.models import Transaction
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.outbox import OutboxRepository
from payflow.db.repositories.transactions import TransactionRepository
from payflow.db.repositories.webhooks import WebhookEventRepository
from payflow.domain.enums import (
    Currency,
    EventType,
    SystemAccount,
    TransactionStatus,
    TransactionType,
)
from payflow.domain.exceptions import AccountNotFoundError, UnknownPaymentError
from payflow.domain.ledger import move
from payflow.domain.ports import PaymentEvent, PaymentProvider, PaymentStatus
from payflow.domain.services.ledger import Ledger

logger = structlog.get_logger(__name__)


def provider_idempotency_key(user_id: UUID, request_key: str) -> str:
    return hashlib.sha256(f"{user_id}:{request_key}".encode()).hexdigest()


class DepositService:
    """Starts provider payments and settles them when the provider reports back."""

    def __init__(
        self, session: AsyncSession, provider: PaymentProvider, clock: Clock
    ) -> None:
        self._session = session
        self._provider = provider
        self._clock = clock
        self._accounts = AccountRepository(session)
        self._transactions = TransactionRepository(session)
        self._webhooks = WebhookEventRepository(session)
        self._outbox = OutboxRepository(session)
        self._ledger = Ledger(session)

    async def start(
        self,
        user_id: UUID,
        currency: Currency,
        amount: Decimal,
        *,
        idempotency_key: str,
    ) -> Transaction:
        """Create a pending deposit backed by a payment at the provider."""
        wallet = await self._accounts.get_wallet(user_id, currency)
        if wallet is None:
            raise AccountNotFoundError
        transaction = Transaction(
            id=uuid7(),
            type=TransactionType.DEPOSIT,
            status=TransactionStatus.PENDING,
            initiator_id=user_id,
            destination_account_id=wallet.id,
            amount=amount,
            currency=currency,
        )
        # the provider deduplicates on this key, so a retry after a crash between
        # its response and our commit resolves to the same payment
        payment = await self._provider.create_payment(
            reference=str(transaction.id),
            amount=amount,
            currency=currency,
            idempotency_key=provider_idempotency_key(user_id, idempotency_key),
        )
        if existing := await self._transactions.get_by_external_id(payment.id):
            return existing
        transaction.external_id = payment.id
        self._transactions.add(transaction)
        await self._session.flush()
        logger.info(
            "deposit.started",
            transaction_id=str(transaction.id),
            payment_id=payment.id,
            amount=str(amount),
            currency=currency,
        )
        return transaction

    async def apply_payment_event(self, event: PaymentEvent) -> None:
        """Apply a provider webhook; repeated or late deliveries change nothing."""
        if not await self._webhooks.record(
            event.event_id, event.event_type, event.payload
        ):
            logger.info("webhook.duplicate", event_id=event.event_id)
            return
        transaction = await self._transactions.lock_by_external_id(event.payment_id)
        if transaction is None:
            raise UnknownPaymentError
        if transaction.status is not TransactionStatus.PENDING:
            logger.info(
                "webhook.ignored",
                event_id=event.event_id,
                transaction_id=str(transaction.id),
                status=transaction.status,
            )
            return
        if (event.amount, event.currency) != (transaction.amount, transaction.currency):
            logger.error(
                "webhook.amount_mismatch",
                event_id=event.event_id,
                transaction_id=str(transaction.id),
                reported=f"{event.amount} {event.currency}",
            )
            self._fail(transaction, "provider reported a different amount")
            return
        match event.status:
            case PaymentStatus.SUCCEEDED:
                await self._settle(transaction)
            case PaymentStatus.FAILED:
                self._fail(transaction, event.failure_reason or "payment failed")
            case PaymentStatus.PENDING:
                return

    async def _settle(self, transaction: Transaction) -> None:
        clearing = await self._accounts.system_account(
            SystemAccount.PROVIDER_CLEARING, transaction.currency
        )
        wallet_id = transaction.destination_account_id
        accounts = await self._ledger.lock(clearing.id, wallet_id)
        await self._ledger.post(
            transaction,
            *move(accounts[clearing.id], accounts[wallet_id], transaction.amount),
        )
        transaction.status = TransactionStatus.COMPLETED
        transaction.completed_at = self._clock()
        self._outbox.publish(EventType.DEPOSIT_COMPLETED, transaction)
        logger.info("deposit.completed", transaction_id=str(transaction.id))

    def _fail(self, transaction: Transaction, reason: str) -> None:
        transaction.status = TransactionStatus.FAILED
        transaction.failure_reason = reason
        self._outbox.publish(EventType.DEPOSIT_FAILED, transaction)
        logger.info("deposit.failed", transaction_id=str(transaction.id), reason=reason)
