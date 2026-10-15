from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Account, LedgerEntry, Transaction
from payflow.db.repositories.accounts import AccountRepository
from payflow.domain.exceptions import AccountNotFoundError, InsufficientFundsError
from payflow.domain.ledger import Posting, ensure_balanced


class Ledger:
    """The only writer of ledger entries and of the balances derived from them."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = AccountRepository(session)
        self._locked: dict[UUID, Account] = {}

    async def lock(self, *account_ids: UUID) -> dict[UUID, Account]:
        """Lock accounts for posting, always in id order."""
        wanted = set(account_ids)
        accounts = await self._accounts.lock(wanted)
        if len(accounts) != len(wanted):
            raise AccountNotFoundError
        locked = {account.id: account for account in accounts}
        self._locked.update(locked)
        return locked

    async def post(self, transaction: Transaction, *postings: Posting) -> None:
        """Write balanced entries and move the balances of the locked accounts."""
        ensure_balanced(postings)
        balances: dict[UUID, Decimal] = {}
        for posting in postings:
            account = self._locked_account(posting.account_id)
            current = balances.get(account.id, account.balance)
            balances[account.id] = current + posting.amount
        for account_id, balance in balances.items():
            if balance < 0 and not self._locked[account_id].is_system:
                raise InsufficientFundsError
        for account_id, balance in balances.items():
            self._locked[account_id].balance = balance
        self._session.add_all(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=posting.account_id,
                currency=posting.currency,
                amount=posting.amount,
            )
            for posting in postings
        )
        await self._session.flush()

    def _locked_account(self, account_id: UUID) -> Account:
        try:
            return self._locked[account_id]
        except KeyError:
            raise RuntimeError(f"account {account_id} was not locked") from None
