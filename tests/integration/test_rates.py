import asyncio
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from mock_provider.config import ProviderSettings
from mock_provider.main import create_app as create_provider_app
from payflow.core.clock import utc_now
from payflow.domain.enums import Currency
from payflow.domain.exceptions import RatesUnavailableError
from payflow.integrations.rates import CACHE_KEY, CachedRates, HttpRatesProvider
from tests.integration.fakes import FakeRatesProvider


def cached(
    redis: Redis, provider: FakeRatesProvider, ttl: timedelta = timedelta(minutes=1)
) -> CachedRates:
    return CachedRates(redis, provider, ttl, utc_now)


async def test_rates_are_fetched_once_per_ttl(redis: Redis) -> None:
    provider = FakeRatesProvider()
    rates = cached(redis, provider)

    first = await rates.snapshot()
    second = await rates.snapshot()

    assert provider.calls == 1
    assert first == second
    assert 0 < await redis.ttl(CACHE_KEY) <= 60


async def test_cache_is_shared_between_instances(redis: Redis) -> None:
    provider = FakeRatesProvider()

    await cached(redis, provider).snapshot()
    await cached(redis, provider).snapshot()

    assert provider.calls == 1


async def test_expired_rates_are_refreshed(redis: Redis) -> None:
    provider = FakeRatesProvider()
    rates = cached(redis, provider, ttl=timedelta(milliseconds=100))
    await rates.snapshot()
    provider.usd_kzt = Decimal("510.00")

    await asyncio.sleep(0.2)
    refreshed = await rates.snapshot()

    assert provider.calls == 2
    assert refreshed.mid_rate(Currency.USD, Currency.KZT) == Decimal("510.00")


async def test_concurrent_misses_trigger_one_fetch(redis: Redis) -> None:
    provider = FakeRatesProvider()
    rates = cached(redis, provider)

    await asyncio.gather(*(rates.snapshot() for _ in range(20)))

    assert provider.calls == 1


async def test_outage_without_cache_is_reported(redis: Redis) -> None:
    provider = FakeRatesProvider(available=False)

    with pytest.raises(RatesUnavailableError):
        await cached(redis, provider).snapshot()


async def test_http_provider_reads_mock_feed() -> None:
    feed = create_provider_app(
        ProviderSettings(
            api_key=SecretStr("key"),
            webhook_url="http://unused",
            webhook_secret=SecretStr("secret"),
            log_json=False,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=feed), base_url="http://feed"
    ) as client:
        rates = await HttpRatesProvider(client).usd_rates()

    assert rates[Currency.USD] == 1
    assert Decimal(480) < rates[Currency.KZT] < Decimal(530)


async def test_http_provider_failure_is_reported() -> None:
    broken = httpx.MockTransport(lambda _: httpx.Response(502))
    async with httpx.AsyncClient(transport=broken, base_url="http://feed") as client:
        with pytest.raises(RatesUnavailableError):
            await HttpRatesProvider(client).usd_rates()
