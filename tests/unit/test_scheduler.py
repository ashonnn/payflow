import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest

from payflow.workers.scheduler import (
    run_daily,
    run_every,
    sleep_until_stopped,
    time_until,
)

NOW = datetime(2026, 10, 15, 1, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (time(2, 0), timedelta(minutes=30)),
        (time(1, 30), timedelta(days=1)),
        (time(0, 0), timedelta(hours=22, minutes=30)),
    ],
)
def test_time_until_next_occurrence(at: time, expected: timedelta) -> None:
    assert time_until(at, NOW) == expected


async def test_sleep_is_cut_short_by_stop() -> None:
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.01, stop.set)

    assert await sleep_until_stopped(stop, timedelta(seconds=5))


async def test_sleep_runs_out_without_stop() -> None:
    assert not await sleep_until_stopped(asyncio.Event(), timedelta(milliseconds=5))


async def test_failing_job_does_not_stop_the_schedule() -> None:
    stop = asyncio.Event()
    calls: list[int] = []

    async def flaky() -> None:
        calls.append(len(calls))
        if len(calls) == 3:
            stop.set()
        raise RuntimeError("boom")

    await asyncio.wait_for(
        run_every("flaky", flaky, timedelta(milliseconds=1), stop), timeout=2
    )

    assert len(calls) == 3


async def test_daily_job_runs_at_its_time() -> None:
    stop = asyncio.Event()
    almost_two = datetime(2026, 10, 15, 1, 59, 59, 950_000, tzinfo=UTC)
    runs: list[datetime] = []

    async def job() -> None:
        runs.append(almost_two)
        stop.set()

    await asyncio.wait_for(
        run_daily("nightly", job, time(2, 0), stop, lambda: almost_two), timeout=2
    )

    assert runs == [almost_two]
