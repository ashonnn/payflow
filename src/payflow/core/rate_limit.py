import math
import secrets
from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis

# the script reads redis TIME so every api replica uses the same clock
SLIDING_WINDOW = """
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return tonumber(oldest[2]) + window - now
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """At most `limit` hits per key in any rolling window; rejected hits are not counted."""

    def __init__(
        self, redis: Redis, *, name: str, limit: int, window: timedelta
    ) -> None:
        self._script = redis.register_script(SLIDING_WINDOW)
        self._name = name
        self._limit = limit
        self._window_ms = int(window.total_seconds() * 1000)

    async def hit(self, subject: str) -> RateLimitDecision:
        wait_ms = int(
            await self._script(
                keys=[f"rate-limit:{self._name}:{subject}"],
                args=[self._window_ms, self._limit, secrets.token_hex(8)],
            )
        )
        return RateLimitDecision(
            allowed=wait_ms == 0, retry_after_seconds=math.ceil(wait_ms / 1000)
        )
