import asyncio

from httpx import AsyncClient

from payflow.container import build_container
from payflow.core.config import Settings
from payflow.workers.runner import run_worker
from tests.integration.helpers import Sessions, fund, sign_up


async def test_worker_delivers_events_until_stopped(
    client: AsyncClient, session_factory: Sessions, settings: Settings
) -> None:
    fast = settings.model_copy(update={"outbox_poll_interval_seconds": 0.02})
    container = build_container(fast)
    stop = asyncio.Event()
    worker = asyncio.create_task(run_worker(container, stop))
    user = await sign_up(client, "+77010000001")

    await fund(session_factory, user.id, "300.00")
    async with asyncio.timeout(5):
        while True:
            response = await client.get("/api/v1/notifications", headers=user.headers)
            if response.json():
                break
            await asyncio.sleep(0.02)

    stop.set()
    await asyncio.wait_for(worker, timeout=5)
    await container.aclose()
    assert worker.done()
    assert worker.exception() is None
