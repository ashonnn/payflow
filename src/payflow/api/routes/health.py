import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from fastapi import APIRouter, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import text

from payflow.api.deps import ContainerDep

CHECK_TIMEOUT_SECONDS = 2

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["operations"])

type CheckStatus = Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckStatus]


async def probe(name: str, check: Callable[[], Awaitable[object]]) -> CheckStatus:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await check()
    except Exception:
        logger.warning("health.check_failed", dependency=name, exc_info=True)
        return "unavailable"
    return "ok"


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", responses={503: {"model": HealthResponse}})
async def health(container: ContainerDep, response: Response) -> HealthResponse:
    async def database() -> None:
        async with container.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def redis() -> object:
        return await container.redis.ping()

    checks: dict[str, CheckStatus] = {
        "database": await probe("database", database),
        "redis": await probe("redis", redis),
    }
    healthy = all(result == "ok" for result in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "degraded", checks=checks)


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
