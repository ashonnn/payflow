from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import permutations
from uuid import UUID, uuid7

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.core.clock import Clock
from payflow.core.metrics import EXCHANGES
from payflow.db.models import Account, Transaction
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.outbox import OutboxRepository
from payflow.db.repositories.transactions import TransactionRepository
from payflow.domain.enums import (
    Currency,
    EventType,
    SystemAccount,
    TransactionStatus,
    TransactionType,
)
from payflow.domain.exceptions import (
    AccountNotFoundError,
    ExchangeAmountTooSmallError,
    SameCurrencyExchangeError,
)
from payflow.domain.ledger import move
from payflow.domain.money import RATE_STEP, apply_spread, convert
from payflow.domain.ports import ExchangeRates
from payflow.domain.services.ledger import Ledger

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Quote:
    source: Currency
    target: Currency
    mid_rate: Decimal
    rate: Decimal
    as_of: datetime


class ExchangeService:
    """Converts between a user's own wallets at the cached mid rate minus a spread."""

    def __init__(
        self,
        session: AsyncSession,
        rates: ExchangeRates,
        spread: Decimal,
        clock: Clock,
    ) -> None:
        self._session = session
        self._rates = rates
        self._spread = spread
        self._clock = clock
        self._accounts = AccountRepository(session)
        self._transactions = TransactionRepository(session)
        self._outbox = OutboxRepository(session)
        self._ledger = Ledger(session)

    async def quotes(self) -> list[Quote]:
        snapshot = await self._rates.snapshot()
        return [
            self._quote(
                snapshot.mid_rate(source, target), source, target, snapshot.fetched_at
            )
            for source, target in permutations(Currency, 2)
        ]

    async def quote(self, source: Currency, target: Currency) -> Quote:
        if source == target:
            raise SameCurrencyExchangeError
        snapshot = await self._rates.snapshot()
        return self._quote(
            snapshot.mid_rate(source, target), source, target, snapshot.fetched_at
        )

    async def exchange(
        self, user_id: UUID, source: Currency, target: Currency, amount: Decimal
    ) -> Transaction:
        quote = await self.quote(source, target)
        converted = convert(amount, quote.rate)
        if converted <= 0:
            raise ExchangeAmountTooSmallError
        source_wallet = await self._wallet(user_id, source)
        target_wallet = await self._wallet(user_id, target)
        source_pool = await self._accounts.system_account(SystemAccount.FX_POOL, source)
        target_pool = await self._accounts.system_account(SystemAccount.FX_POOL, target)
        accounts = await self._ledger.lock(
            source_wallet.id, target_wallet.id, source_pool.id, target_pool.id
        )
        transaction = Transaction(
            id=uuid7(),
            type=TransactionType.EXCHANGE,
            status=TransactionStatus.COMPLETED,
            initiator_id=user_id,
            source_account_id=source_wallet.id,
            destination_account_id=target_wallet.id,
            amount=amount,
            currency=source,
            counter_amount=converted,
            counter_currency=target,
            exchange_rate=quote.rate,
            completed_at=self._clock(),
        )
        self._transactions.add(transaction)
        await self._session.flush()
        await self._ledger.post(
            transaction,
            *move(accounts[source_wallet.id], accounts[source_pool.id], amount),
            *move(accounts[target_pool.id], accounts[target_wallet.id], converted),
        )
        self._outbox.publish(EventType.EXCHANGE_COMPLETED, transaction)
        EXCHANGES.labels(f"{source}/{target}").inc()
        logger.info(
            "exchange.completed",
            transaction_id=str(transaction.id),
            pair=f"{source}/{target}",
            rate=str(quote.rate),
        )
        return transaction

    def _quote(
        self, mid_rate: Decimal, source: Currency, target: Currency, as_of: datetime
    ) -> Quote:
        return Quote(
            source=source,
            target=target,
            mid_rate=mid_rate.quantize(RATE_STEP),
            rate=apply_spread(mid_rate, self._spread),
            as_of=as_of,
        )

    async def _wallet(self, user_id: UUID, currency: Currency) -> Account:
        wallet = await self._accounts.get_wallet(user_id, currency)
        if wallet is None:
            raise AccountNotFoundError
        return wallet
