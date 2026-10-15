from datetime import UTC, datetime, timedelta
from uuid import uuid7

import jwt
import pytest

from payflow.core.clock import utc_now
from payflow.core.security import PasswordHasher, TokenCodec, TokenType

SECRET = "unit-test-secret-that-is-long-enough"


@pytest.fixture(scope="module")
def hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=1, memory_kib=1024, parallelism=1)


@pytest.fixture
def codec() -> TokenCodec:
    return TokenCodec(SECRET, "HS256", utc_now)


async def test_password_round_trip(hasher: PasswordHasher) -> None:
    password_hash = await hasher.hash("correct-horse")

    assert await hasher.verify(password_hash, "correct-horse")
    assert not await hasher.verify(password_hash, "wrong-horse")


async def test_verify_rejects_malformed_hash(hasher: PasswordHasher) -> None:
    assert not await hasher.verify("not-an-argon2-hash", "anything")


def test_token_round_trip(codec: TokenCodec) -> None:
    subject = uuid7()
    token, issued = codec.issue(subject, TokenType.ACCESS, timedelta(minutes=5))

    decoded = codec.decode(token, TokenType.ACCESS)

    assert decoded is not None
    assert decoded.subject == subject
    assert decoded.token_id == issued.token_id


def test_token_of_other_type_is_rejected(codec: TokenCodec) -> None:
    token, _ = codec.issue(uuid7(), TokenType.REFRESH, timedelta(minutes=5))

    assert codec.decode(token, TokenType.ACCESS) is None


def test_expired_token_is_rejected() -> None:
    issued_an_hour_ago = TokenCodec(
        SECRET, "HS256", lambda: datetime.now(UTC) - timedelta(hours=1)
    )
    token, _ = issued_an_hour_ago.issue(uuid7(), TokenType.ACCESS, timedelta(minutes=5))

    assert issued_an_hour_ago.decode(token, TokenType.ACCESS) is None


def test_token_signed_with_other_secret_is_rejected(codec: TokenCodec) -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid7()),
            "type": "access",
            "jti": "x",
            "exp": utc_now() + timedelta(1),
        },
        "another-secret-that-is-long-enough!",
        algorithm="HS256",
    )

    assert codec.decode(forged, TokenType.ACCESS) is None


def test_token_without_required_claims_is_rejected(codec: TokenCodec) -> None:
    incomplete = jwt.encode(
        {"sub": str(uuid7()), "exp": utc_now() + timedelta(1)},
        SECRET,
        algorithm="HS256",
    )

    assert codec.decode(incomplete, TokenType.ACCESS) is None
