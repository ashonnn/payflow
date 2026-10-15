from datetime import timedelta

import structlog

from payflow.container import Container
from payflow.db.models import ReconciliationReport
from payflow.db.repositories.idempotency import IdempotencyRepository
from payflow.domain.services.reconciliation import ReconciliationService
from payflow.workers.locks import advisory_lock

logger = structlog.get_logger(__name__)


async def reconcile(container: Container) -> ReconciliationReport | None:
    """Run reconciliation unless another worker is already doing it."""
    async with advisory_lock(container.engine, "reconciliation") as acquired:
        if not acquired:
            logger.info("reconciliation.skipped", reason="running in another worker")
            return None
        service = ReconciliationService(container.session_factory, container.clock)
        return await service.run()


async def purge_idempotency_keys(container: Container) -> int:
    ttl = timedelta(hours=container.settings.idempotency_key_ttl_hours)
    async with container.session_factory.begin() as session:
        purged = await IdempotencyRepository(session).purge_created_before(
            container.clock() - ttl
        )
    logger.info("idempotency_keys.purged", count=purged)
    return purged
