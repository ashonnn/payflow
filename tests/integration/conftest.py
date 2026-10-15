import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from payflow.container import Container, build_container
from payflow.core.config import Settings
from payflow.db.base import Base
from payflow.db.session import build_engine, build_session_factory
from payflow.main import create_app

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    if url := os.environ.get("TEST_REDIS_URL"):
        yield url
        return
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(container.port)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def settings(database_url: str, redis_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        log_json=False,
        database_url=database_url,
        database_pool_size=20,
        database_max_overflow=30,
        redis_url=redis_url,
        jwt_secret=SecretStr("test-jwt-secret-with-enough-entropy"),
        password_hash_time_cost=1,
        password_hash_memory_kib=1024,
        admin_session_secret=SecretStr("test-admin-session-secret"),
        payment_provider_url="http://mock-provider",
        payment_provider_api_key=SecretStr("test-provider-key"),
        payment_provider_webhook_secret=SecretStr("test-webhook-secret"),
        fx_provider_url="http://mock-provider",
    )


def apply_migrations(database_url: str) -> None:
    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    # alembic's env.py calls asyncio.run, which cannot nest inside the test loop
    await asyncio.to_thread(apply_migrations, settings.database_url)
    engine = build_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return build_session_factory(engine)


@pytest.fixture(scope="session")
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
async def clean_state(engine: AsyncEngine, redis: Redis) -> None:
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await redis.flushdb()


@pytest.fixture
async def app(settings: Settings, engine: AsyncEngine) -> AsyncIterator[FastAPI]:
    app = create_app(build_container(settings))
    async with LifespanManager(app):
        yield app


@pytest.fixture
def container(app: FastAPI) -> Container:
    container: Container = app.state.container
    return container


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
