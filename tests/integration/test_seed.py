from uuid import UUID

from httpx import AsyncClient
from pydantic import SecretStr

from payflow.container import Container
from payflow.domain.enums import ReconciliationStatus
from payflow.seed import ADMIN, SeedSettings, seed
from payflow.workers.jobs import reconcile
from tests.integration.helpers import ApiUser, balances

SETTINGS = SeedSettings(
    _env_file=None,
    admin_password=SecretStr("admin-demo-pass"),
    user_password=SecretStr("user-demo-pass"),
)


async def log_in(client: AsyncClient, phone: str, password: str) -> ApiUser:
    response = await client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": password}
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = (await client.get("/api/v1/me", headers=headers)).json()
    return ApiUser(id=UUID(me["id"]), phone=phone, headers=headers)


async def test_seed_runs_once(container: Container) -> None:
    assert await seed(container, SETTINGS)
    assert not await seed(container, SETTINGS)


async def test_seeded_balances_follow_the_ledger(
    client: AsyncClient, container: Container
) -> None:
    await seed(container, SETTINGS)

    aruzhan = await log_in(client, "+77010000001", "user-demo-pass")
    daniyar = await log_in(client, "+77010000002", "user-demo-pass")
    madina = await log_in(client, "+77010000003", "user-demo-pass")

    assert await balances(client, aruzhan) == {"KZT": "1287000.00", "USD": "1200.00"}
    assert await balances(client, daniyar) == {"KZT": "330500.00", "USD": "300.00"}
    assert await balances(client, madina) == {"KZT": "97500.00", "USD": "0.00"}
    report = await reconcile(container)
    assert report is not None
    assert report.status is ReconciliationStatus.OK


async def test_seeded_admin_sees_the_held_transfer(
    client: AsyncClient, container: Container
) -> None:
    await seed(container, SETTINGS)
    admin = await log_in(client, ADMIN.phone, "admin-demo-pass")

    reviews = await client.get("/api/v1/admin/reviews", headers=admin.headers)

    assert [(r["amount"], r["review_reasons"]) for r in reviews.json()] == [
        ("1200000.00", ["large_amount", "new_recipient"])
    ]
