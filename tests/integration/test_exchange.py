from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select

from payflow.db.models import Account
from payflow.domain.enums import Currency, SystemAccount
from tests.integration.fakes import FakeRatesProvider
from tests.integration.helpers import ApiUser, Sessions, balances, fund, sign_up


@pytest.fixture
async def user(client: AsyncClient, session_factory: Sessions) -> ApiUser:
    user = await sign_up(client, "+77012223344")
    await fund(session_factory, user.id, "100.00", Currency.USD)
    await fund(session_factory, user.id, "10000.00", Currency.KZT)
    return user


async def exchange(
    client: AsyncClient,
    user: ApiUser,
    amount: str,
    source: str = "USD",
    target: str = "KZT",
    *,
    key: str | None = None,
) -> Response:
    return await client.post(
        "/api/v1/exchanges",
        json={"from_currency": source, "to_currency": target, "amount": amount},
        headers={**user.headers, "Idempotency-Key": key or str(uuid4())},
    )


async def pool_balances(sessions: Sessions) -> dict[Currency, Decimal]:
    async with sessions() as session:
        rows = await session.execute(
            select(Account.currency, Account.balance).where(
                Account.system_code == SystemAccount.FX_POOL
            )
        )
        return dict(rows.tuples().all())


async def test_rates_include_spread_for_both_directions(
    client: AsyncClient, rates_provider: FakeRatesProvider
) -> None:
    response = await client.get("/api/v1/exchange/rates")

    quotes = {(q["source"], q["target"]): q for q in response.json()}
    assert quotes["USD", "KZT"]["mid_rate"] == "500.00000000"
    assert quotes["USD", "KZT"]["rate"] == "497.50000000"
    assert quotes["KZT", "USD"]["mid_rate"] == "0.00200000"
    assert quotes["KZT", "USD"]["rate"] == "0.00199000"


async def test_exchange_moves_money_through_fx_pool(
    client: AsyncClient,
    user: ApiUser,
    rates_provider: FakeRatesProvider,
    session_factory: Sessions,
) -> None:
    response = await exchange(client, user, "100.00")

    assert response.status_code == 201
    body = response.json()
    assert body["direction"] == "internal"
    assert (body["amount"], body["currency"]) == ("100.00", "USD")
    assert (body["counter_amount"], body["counter_currency"]) == ("49750.00", "KZT")
    assert body["exchange_rate"] == "497.50000000"
    assert await balances(client, user) == {"KZT": "59750.00", "USD": "0.00"}
    assert await pool_balances(session_factory) == {
        Currency.USD: Decimal("100.00"),
        Currency.KZT: Decimal("-49750.00"),
    }


async def test_exchange_back_uses_inverse_rate(
    client: AsyncClient, user: ApiUser, rates_provider: FakeRatesProvider
) -> None:
    response = await exchange(client, user, "10000.00", "KZT", "USD")

    assert response.json()["counter_amount"] == "19.90"
    assert await balances(client, user) == {"KZT": "0.00", "USD": "119.90"}


async def test_rates_are_cached_between_exchanges(
    client: AsyncClient, user: ApiUser, rates_provider: FakeRatesProvider
) -> None:
    await exchange(client, user, "10.00")
    await exchange(client, user, "10.00")
    await client.get("/api/v1/exchange/rates")

    assert rates_provider.calls == 1


@pytest.mark.parametrize(
    ("amount", "source", "target", "status_code", "code"),
    [
        ("100.01", "USD", "KZT", 409, "insufficient_funds"),
        ("10.00", "USD", "USD", 422, "same_currency"),
        ("0.01", "KZT", "USD", 422, "amount_too_small"),
    ],
)
async def test_invalid_exchanges_are_rejected(
    client: AsyncClient,
    user: ApiUser,
    rates_provider: FakeRatesProvider,
    amount: str,
    source: str,
    target: str,
    status_code: int,
    code: str,
) -> None:
    response = await exchange(client, user, amount, source, target)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert await balances(client, user) == {"KZT": "10000.00", "USD": "100.00"}


async def test_rates_outage_returns_503(
    client: AsyncClient, user: ApiUser, rates_provider: FakeRatesProvider
) -> None:
    rates_provider.available = False

    response = await exchange(client, user, "10.00")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rates_unavailable"


async def test_exchange_retry_converts_once(
    client: AsyncClient, user: ApiUser, rates_provider: FakeRatesProvider
) -> None:
    first = await exchange(client, user, "50.00", key="fx-1")
    retry = await exchange(client, user, "50.00", key="fx-1")

    assert retry.json() == first.json()
    assert (await balances(client, user))["USD"] == "50.00"
