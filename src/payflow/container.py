from dataclasses import dataclass
from datetime import timedelta

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from payflow.core.clock import Clock, utc_now
from payflow.core.config import Settings
from payflow.core.rate_limit import SlidingWindowRateLimiter
from payflow.core.security import PasswordHasher, TokenCodec
from payflow.db.session import build_engine, build_session_factory
from payflow.domain.fraud import FraudPolicy
from payflow.domain.ports import ExchangeRates, PaymentProvider
from payflow.integrations.payment_provider import HttpPaymentProvider, WebhookVerifier
from payflow.integrations.rates import CachedRates, HttpRatesProvider


@dataclass(slots=True, kw_only=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    provider_client: httpx.AsyncClient
    fx_client: httpx.AsyncClient
    password_hasher: PasswordHasher
    token_codec: TokenCodec
    payment_provider: PaymentProvider
    webhook_verifier: WebhookVerifier
    exchange_rates: ExchangeRates
    fraud_policy: FraudPolicy
    transfer_rate_limiter: SlidingWindowRateLimiter
    clock: Clock

    async def aclose(self) -> None:
        await self.provider_client.aclose()
        await self.fx_client.aclose()
        await self.redis.aclose()
        await self.engine.dispose()


def build_container(
    settings: Settings, *, http_transport: httpx.AsyncBaseTransport | None = None
) -> Container:
    engine = build_engine(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    provider_client = httpx.AsyncClient(
        base_url=settings.payment_provider_url,
        timeout=settings.payment_provider_timeout_seconds,
        transport=http_transport,
    )
    fx_client = httpx.AsyncClient(
        base_url=settings.fx_provider_url,
        timeout=settings.fx_provider_timeout_seconds,
        transport=http_transport,
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        redis=redis,
        provider_client=provider_client,
        fx_client=fx_client,
        password_hasher=PasswordHasher(
            time_cost=settings.password_hash_time_cost,
            memory_kib=settings.password_hash_memory_kib,
            parallelism=settings.password_hash_parallelism,
        ),
        token_codec=TokenCodec(
            settings.jwt_secret.get_secret_value(), settings.jwt_algorithm, utc_now
        ),
        payment_provider=HttpPaymentProvider(
            provider_client, settings.payment_provider_api_key.get_secret_value()
        ),
        webhook_verifier=WebhookVerifier(
            settings.payment_provider_webhook_secret.get_secret_value(),
            timedelta(seconds=settings.webhook_tolerance_seconds),
            utc_now,
        ),
        exchange_rates=CachedRates(
            redis,
            HttpRatesProvider(fx_client),
            timedelta(seconds=settings.fx_rates_ttl_seconds),
            utc_now,
        ),
        fraud_policy=FraudPolicy.from_settings(settings.fraud),
        transfer_rate_limiter=SlidingWindowRateLimiter(
            redis,
            name="transfers",
            limit=settings.transfer_rate_limit,
            window=timedelta(seconds=settings.transfer_rate_window_seconds),
        ),
        clock=utc_now,
    )
