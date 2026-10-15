from httpx import AsyncClient
from redis.asyncio import Redis

from payflow.container import Container
from tests.integration.helpers import Sessions, fund, send_transfer, sign_up


async def test_health_reports_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


async def test_health_degrades_when_redis_is_down(
    client: AsyncClient, container: Container
) -> None:
    healthy_redis = container.redis
    container.redis = Redis.from_url("redis://127.0.0.1:1/0")
    try:
        response = await client.get("/health")
    finally:
        await container.redis.aclose()
        container.redis = healthy_redis

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "unavailable"}


async def test_liveness_needs_no_dependencies(client: AsyncClient) -> None:
    assert (await client.get("/health/live")).json() == {"status": "ok"}


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    generated = await client.get("/health/live")
    echoed = await client.get("/health/live", headers={"X-Request-ID": "trace-123"})
    rejected = await client.get("/health/live", headers={"X-Request-ID": "bad id!"})

    assert len(generated.headers["X-Request-ID"]) == 32
    assert echoed.headers["X-Request-ID"] == "trace-123"
    assert rejected.headers["X-Request-ID"] != "bad id!"


async def test_metrics_expose_http_and_business_counters(
    client: AsyncClient, session_factory: Sessions
) -> None:
    alice = await sign_up(client, "+77010000001")
    bob = await sign_up(client, "+77010000002")
    await fund(session_factory, alice.id, "100.00")
    await send_transfer(client, alice, bob.phone, "10.00")
    await client.get(f"/api/v1/transactions/{alice.id}", headers=alice.headers)

    body = (await client.get("/metrics")).text

    assert (
        'payflow_http_requests_total{method="POST",route="/api/v1/transfers",'
        'status="201"}' in body
    )
    assert (
        'payflow_http_requests_total{method="GET",'
        'route="/api/v1/transactions/{transaction_id}",status="404"}' in body
    )
    assert 'payflow_transfers_total{currency="KZT",status="completed"}' in body
    assert "payflow_http_request_duration_seconds_bucket" in body
