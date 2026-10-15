import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@asynccontextmanager
async def advisory_lock(engine: AsyncEngine, name: str) -> AsyncIterator[bool]:
    """Try to take a cluster-wide lock; yields whether this process holds it."""
    key = zlib.crc32(name.encode())
    async with engine.connect() as connection:
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
        )
        # the lock is session-level, so it survives this commit and the connection
        # does not sit idle in a transaction while the job runs
        await connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )
                await connection.commit()
