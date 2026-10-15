import asyncio
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from payflow.core.clock import Clock
from payflow.core.metrics import FX_RATE_CACHE
from payflow.domain.enums import Currency
from payflow.domain.exceptions import RatesUnavailableError
from payflow.domain.ports import RateSnapshot, RatesProvider

CACHE_KEY = "fx:usd-rates"


class _RatesResponse(BaseModel):
    base: Currency
    rates: dict[str, Decimal]


class HttpRatesProvider:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def usd_rates(self) -> Mapping[Currency, Decimal]:
        try:
            response = await self._client.get("/v1/rates")
            response.raise_for_status()
            body = _RatesResponse.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise RatesUnavailableError from exc
        if body.base is not Currency.USD:
            raise RatesUnavailableError(f"unexpected rate base {body.base}")
        rates = {Currency.USD: Decimal(1)}
        rates.update(
            (Currency(code), rate)
            for code, rate in body.rates.items()
            if code in Currency
        )
        return rates


class CachedRates:
    """Rates shared through Redis, so the provider is asked at most once per TTL."""

    def __init__(
        self, redis: Redis, provider: RatesProvider, ttl: timedelta, clock: Clock
    ) -> None:
        self._redis = redis
        self._provider = provider
        self._ttl = ttl
        self._clock = clock
        self._refresh = asyncio.Lock()

    async def snapshot(self) -> RateSnapshot:
        if cached := await self._cached():
            FX_RATE_CACHE.labels("hit").inc()
            return cached
        # one refresh per process; concurrent misses wait and reuse its result
        async with self._refresh:
            if cached := await self._cached():
                FX_RATE_CACHE.labels("hit").inc()
                return cached
            FX_RATE_CACHE.labels("miss").inc()
            snapshot = RateSnapshot(await self._provider.usd_rates(), self._clock())
            await self._redis.set(CACHE_KEY, _encode(snapshot), px=self._ttl)
            return snapshot

    async def _cached(self) -> RateSnapshot | None:
        raw = await self._redis.get(CACHE_KEY)
        return _decode(raw) if raw else None


def _encode(snapshot: RateSnapshot) -> str:
    return json.dumps(
        {
            "rates": {
                currency: str(rate) for currency, rate in snapshot.usd_rates.items()
            },
            "fetched_at": snapshot.fetched_at.isoformat(),
        }
    )


def _decode(raw: str | bytes) -> RateSnapshot:
    data = json.loads(raw)
    return RateSnapshot(
        usd_rates={
            Currency(code): Decimal(rate) for code, rate in data["rates"].items()
        },
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
    )
