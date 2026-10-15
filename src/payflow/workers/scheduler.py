import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta

import structlog

from payflow.core.clock import Clock

logger = structlog.get_logger(__name__)

type Job = Callable[[], Awaitable[object]]


async def sleep_until_stopped(stop: asyncio.Event, delay: timedelta) -> bool:
    """Sleep for `delay` or until `stop` is set; True if the sleep was cut short."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay.total_seconds())
    except TimeoutError:
        return False
    return True


def time_until(at: time, now: datetime) -> timedelta:
    """Time from `now` until the next occurrence of `at` in now's timezone."""
    run_at = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at - now


async def run_daily(
    name: str, job: Job, at: time, stop: asyncio.Event, clock: Clock
) -> None:
    while not stop.is_set():
        delay = time_until(at, clock())
        logger.info("job.scheduled", job=name, in_seconds=int(delay.total_seconds()))
        if await sleep_until_stopped(stop, delay):
            return
        await _run(name, job)


async def run_every(
    name: str, job: Job, interval: timedelta, stop: asyncio.Event
) -> None:
    while not await sleep_until_stopped(stop, interval):
        await _run(name, job)


async def _run(name: str, job: Job) -> None:
    try:
        await job()
    except Exception:
        logger.exception("job.failed", job=name)
