import argparse
import asyncio
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from payflow.container import build_container
from payflow.core.config import Settings, get_settings
from payflow.core.logging import configure_logging
from payflow.domain.enums import ReconciliationStatus
from payflow.workers.jobs import reconcile
from payflow.workers.runner import run_worker, stop_on_signals

type Command = Callable[[Settings], Coroutine[Any, Any, int]]


async def worker(settings: Settings) -> int:
    container = build_container(settings)
    stop = asyncio.Event()
    stop_on_signals(stop)
    try:
        await run_worker(container, stop)
    finally:
        await container.aclose()
    return 0


async def reconcile_once(settings: Settings) -> int:
    """Exit status 1 when the ledger and the stored balances disagree."""
    container = build_container(settings)
    try:
        report = await reconcile(container)
    finally:
        await container.aclose()
    if report is None or report.status is ReconciliationStatus.OK:
        return 0
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="payflow")
    commands = parser.add_subparsers(required=True)
    commands.add_parser(
        "worker", help="run the outbox relay and scheduled jobs"
    ).set_defaults(command=worker)
    commands.add_parser(
        "reconcile", help="check every balance against the ledger once"
    ).set_defaults(command=reconcile_once)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    command: Command = args.command
    return asyncio.run(command(settings))


if __name__ == "__main__":
    raise SystemExit(main())
