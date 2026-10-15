import random
import uuid
from http import HTTPStatus

from locust import HttpUser, between, task

PASSWORD = "load-test-password"
SEEDED_PHONES = ("+77010000001", "+77010000002", "+77010000003")
EXPECTED_REJECTIONS = {HTTPStatus.CONFLICT, HTTPStatus.TOO_MANY_REQUESTS}


class WalletUser(HttpUser):
    """A customer who tops up once, then browses and sends small transfers."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        phone = f"+7709{random.randint(0, 9_999_999):07d}"
        self.client.post(
            "/api/v1/auth/register",
            json={"phone": phone, "password": PASSWORD, "full_name": "Load Test"},
        )
        tokens = self.client.post(
            "/api/v1/auth/login", json={"phone": phone, "password": PASSWORD}
        ).json()
        self.client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        self.client.post(
            "/api/v1/deposits",
            json={"currency": "KZT", "amount": "200000.00"},
            headers=self._idempotency_key(),
        )

    @task(5)
    def balances(self) -> None:
        self.client.get("/api/v1/accounts")

    @task(3)
    def history(self) -> None:
        self.client.get("/api/v1/transactions", params={"limit": 20})

    @task(2)
    def rates(self) -> None:
        self.client.get("/api/v1/exchange/rates")

    @task(2)
    def transfer(self) -> None:
        self._post_expecting_rejections(
            "/api/v1/transfers",
            {
                "to_phone": random.choice(SEEDED_PHONES),
                "amount": f"{random.randint(100, 5000)}.00",
                "currency": "KZT",
            },
        )

    @task(1)
    def exchange(self) -> None:
        self._post_expecting_rejections(
            "/api/v1/exchanges",
            {"from_currency": "KZT", "to_currency": "USD", "amount": "5000.00"},
        )

    def _post_expecting_rejections(self, path: str, payload: dict[str, str]) -> None:
        with self.client.post(
            path, json=payload, headers=self._idempotency_key(), catch_response=True
        ) as response:
            if response.status_code in EXPECTED_REJECTIONS:
                response.success()

    @staticmethod
    def _idempotency_key() -> dict[str, str]:
        return {"Idempotency-Key": str(uuid.uuid4())}
