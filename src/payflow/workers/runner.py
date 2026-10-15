import asyncio
import contextlib
import signal
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from payflow.container import Container
from payflow.db.models import OutboxEvent
from payflow.domain.services.notifications import NotificationService
from payflow.workers.jobs import purge_idempotency_keys, reconcile
from payflow.workers.outbox import OutboxRelay
from payflow.workers.scheduler import run_daily, run_every

IDEMPOTENCY_PURGE_INTERVAL = timedelta(hours=1)


async def notify(session: AsyncSession, event: OutboxEvent) -> None:
    await NotificationService(session).notify(event)


def build_relay(container: Container) -> OutboxRelay:
    settings = container.settings
    return OutboxRelay(
        container.session_factory,
        notify,
        batch_size=settings.outbox_batch_size,
        max_attempts=settings.outbox_max_attempts,
        retry_base=timedelta(seconds=settings.outbox_retry_base_seconds),
        poll_interval=timedelta(seconds=settings.outbox_poll_interval_seconds),
    )


async def run_worker(container: Container, stop: asyncio.Event) -> None:
    """Run the outbox relay and the scheduled jobs until `stop` is set."""
    settings = container.settings
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(build_relay(container).run(stop))
        tasks.create_task(
            run_daily(
                "reconciliation",
                lambda: reconcile(container),
                settings.reconciliation_run_at,
                stop,
                container.clock,
            )
        )
        tasks.create_task(
            run_every(
                "idempotency_key_purge",
                lambda: purge_idempotency_keys(container),
                IDEMPOTENCY_PURGE_INTERVAL,
                stop,
            )
        )


def stop_on_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        # windows event loops cannot install signal handlers; ctrl+c still works there
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
