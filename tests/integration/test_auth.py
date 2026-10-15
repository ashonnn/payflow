from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.db.models import User
from tests.integration.helpers import DEFAULT_PASSWORD, sign_up

PHONE = "+77011234567"


async def login(
    client: AsyncClient, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"phone": PHONE, "password": password}
    )
    assert response.status_code == 200, response.text
    tokens: dict[str, str] = response.json()
    return tokens


async def test_register_normalizes_input_and_opens_wallets(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "phone": "8 701 123 45 67",
            "password": DEFAULT_PASSWORD,
            "full_name": "  Aruzhan Sadykova ",
        },
    )

    assert response.status_code == 201
    assert response.json()["phone"] == PHONE
    assert response.json()["full_name"] == "Aruzhan Sadykova"

    tokens = await login(client)
    accounts = await client.get(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert [(a["currency"], a["balance"]) for a in accounts.json()] == [
        ("KZT", "0.00"),
        ("USD", "0.00"),
    ]


async def test_register_rejects_duplicate_phone(client: AsyncClient) -> None:
    await sign_up(client, PHONE)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "phone": "+7 701 123 4567",
            "password": DEFAULT_PASSWORD,
            "full_name": "X",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "phone_already_registered"


async def test_register_reports_every_invalid_field(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": "12", "password": "short", "full_name": ""},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {tuple(d["location"]) for d in error["details"]} == {
        ("body", "phone"),
        ("body", "password"),
        ("body", "full_name"),
    }


async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    await sign_up(client, PHONE)

    response = await client.post(
        "/api/v1/auth/login", json={"phone": PHONE, "password": "not-the-password"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_login_rejects_unknown_phone(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"phone": PHONE, "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_refresh_rotates_and_invalidates_old_token(client: AsyncClient) -> None:
    await sign_up(client, PHONE)
    first = await login(client)

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    replayed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )

    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != first["refresh_token"]
    assert replayed.status_code == 401
    me = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert me.json()["phone"] == PHONE


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await sign_up(client, PHONE)
    tokens = await login(client)

    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert logout.status_code == 204
    assert refresh.status_code == 401


async def test_tokens_are_not_interchangeable(client: AsyncClient) -> None:
    await sign_up(client, PHONE)
    tokens = await login(client)

    as_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    as_access = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )

    assert as_refresh.status_code == 401
    assert as_access.status_code == 401


async def test_me_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "missing bearer token"


async def test_deactivated_user_is_rejected(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await sign_up(client, PHONE)
    async with session_factory.begin() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(is_active=False)
        )

    response = await client.get("/api/v1/me", headers=user.headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"


async def test_unknown_route_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}
