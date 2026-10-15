from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from payflow.core.clock import Clock, utc_now
from payflow.core.config import Settings
from payflow.core.security import PasswordHasher, TokenCodec
from payflow.db.session import build_engine, build_session_factory


@dataclass(slots=True, kw_only=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    password_hasher: PasswordHasher
    token_codec: TokenCodec
    clock: Clock

    async def aclose(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()


def build_container(settings: Settings) -> Container:
    engine = build_engine(settings)
    return Container(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        redis=Redis.from_url(settings.redis_url, decode_responses=True),
        password_hasher=PasswordHasher(
            time_cost=settings.password_hash_time_cost,
            memory_kib=settings.password_hash_memory_kib,
            parallelism=settings.password_hash_parallelism,
        ),
        token_codec=TokenCodec(
            settings.jwt_secret.get_secret_value(), settings.jwt_algorithm, utc_now
        ),
        clock=utc_now,
    )
