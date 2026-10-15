from dataclasses import dataclass
from uuid import UUID

from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse-battery"


@dataclass(frozen=True, slots=True)
class ApiUser:
    id: UUID
    phone: str
    headers: dict[str, str]


async def sign_up(
    client: AsyncClient,
    phone: str,
    *,
    full_name: str = "Test User",
    password: str = DEFAULT_PASSWORD,
) -> ApiUser:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": password, "full_name": full_name},
    )
    assert registered.status_code == 201, registered.text
    tokens = await client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": password}
    )
    assert tokens.status_code == 200, tokens.text
    return ApiUser(
        id=UUID(registered.json()["id"]),
        phone=registered.json()["phone"],
        headers={"Authorization": f"Bearer {tokens.json()['access_token']}"},
    )
