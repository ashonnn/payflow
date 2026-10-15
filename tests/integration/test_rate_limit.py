import asyncio
from datetime import timedelta

from redis.asyncio import Redis

from payflow.core.rate_limit import SlidingWindowRateLimiter


def limiter(redis: Redis, limit: int, window: timedelta) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(redis, name="test", limit=limit, window=window)


async def test_allows_limit_then_reports_wait(redis: Redis) -> None:
    transfers = limiter(redis, 3, timedelta(minutes=1))

    decisions = [await transfers.hit("user-1") for _ in range(4)]

    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert 0 < decisions[-1].retry_after_seconds <= 60


async def test_limits_are_tracked_per_subject(redis: Redis) -> None:
    transfers = limiter(redis, 1, timedelta(minutes=1))

    assert (await transfers.hit("user-1")).allowed
    assert not (await transfers.hit("user-1")).allowed
    assert (await transfers.hit("user-2")).allowed


async def test_window_slides(redis: Redis) -> None:
    transfers = limiter(redis, 2, timedelta(milliseconds=200))
    await transfers.hit("user-1")
    await transfers.hit("user-1")

    assert not (await transfers.hit("user-1")).allowed
    await asyncio.sleep(0.25)
    assert (await transfers.hit("user-1")).allowed


async def test_concurrent_hits_never_exceed_limit(redis: Redis) -> None:
    transfers = limiter(redis, 10, timedelta(minutes=1))

    decisions = await asyncio.gather(*(transfers.hit("user-1") for _ in range(50)))

    assert sum(decision.allowed for decision in decisions) == 10
