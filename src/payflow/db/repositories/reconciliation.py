from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Account, LedgerEntry, ReconciliationReport


class ReconciliationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_accounts(self) -> int:
        return await self._session.scalar(select(func.count(Account.id))) or 0

    async def balance_drift(self) -> list[dict[str, Any]]:
        """Accounts whose stored balance differs from the sum of their entries."""
        ledger_total = func.coalesce(func.sum(LedgerEntry.amount), 0)
        rows = await self._session.execute(
            select(Account.id, Account.currency, Account.balance, ledger_total)
            .outerjoin(LedgerEntry, LedgerEntry.account_id == Account.id)
            .group_by(Account.id)
            .having(Account.balance != ledger_total)
            .order_by(Account.id)
        )
        return [
            {
                "account_id": str(account_id),
                "currency": currency,
                "stored_balance": str(balance),
                "ledger_balance": str(total),
            }
            for account_id, currency, balance, total in rows
        ]

    async def unbalanced_transactions(self) -> list[dict[str, Any]]:
        imbalance = func.sum(LedgerEntry.amount)
        rows = await self._session.execute(
            select(LedgerEntry.transaction_id, LedgerEntry.currency, imbalance)
            .group_by(LedgerEntry.transaction_id, LedgerEntry.currency)
            .having(imbalance != 0)
            .order_by(LedgerEntry.transaction_id)
        )
        return [
            {
                "transaction_id": str(transaction_id),
                "currency": currency,
                "imbalance": str(total),
            }
            for transaction_id, currency, total in rows
        ]

    async def nonzero_currency_totals(self) -> list[dict[str, Any]]:
        total = func.sum(LedgerEntry.amount)
        rows = await self._session.execute(
            select(LedgerEntry.currency, total)
            .group_by(LedgerEntry.currency)
            .having(total != 0)
        )
        return [
            {"currency": currency, "total": str(amount)} for currency, amount in rows
        ]

    def add_report(self, report: ReconciliationReport) -> None:
        self._session.add(report)
