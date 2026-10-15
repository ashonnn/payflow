from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.core.clock import Clock
from payflow.core.metrics import RECONCILIATION_FINISHED_AT, RECONCILIATION_ISSUES
from payflow.db.models import ReconciliationReport
from payflow.db.repositories.reconciliation import ReconciliationRepository
from payflow.domain.enums import ReconciliationStatus

logger = structlog.get_logger(__name__)


class ReconciliationService:
    """Recomputes every balance from the ledger and records any drift it finds."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def run(self) -> ReconciliationReport:
        started_at = self._clock()
        async with self._session_factory() as session:
            # every check reads the same snapshot, so postings that commit while
            # the job runs cannot show up as drift
            await session.connection(
                execution_options={
                    "isolation_level": "REPEATABLE READ",
                    "postgresql_readonly": True,
                }
            )
            checks = ReconciliationRepository(session)
            accounts_checked = await checks.count_accounts()
            issues = [
                *_issues("balance_drift", await checks.balance_drift()),
                *_issues(
                    "unbalanced_transaction", await checks.unbalanced_transactions()
                ),
                *_issues(
                    "nonzero_currency_total", await checks.nonzero_currency_totals()
                ),
            ]
        report = ReconciliationReport(
            status=ReconciliationStatus.MISMATCH if issues else ReconciliationStatus.OK,
            accounts_checked=accounts_checked,
            issues=issues,
            started_at=started_at,
            finished_at=self._clock(),
        )
        async with self._session_factory.begin() as session:
            ReconciliationRepository(session).add_report(report)
        RECONCILIATION_ISSUES.set(len(issues))
        RECONCILIATION_FINISHED_AT.set(report.finished_at.timestamp())
        log = logger.error if issues else logger.info
        log(
            "reconciliation.finished",
            status=report.status,
            accounts_checked=accounts_checked,
            issues=len(issues),
        )
        return report


def _issues(kind: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"kind": kind, **row} for row in rows]
