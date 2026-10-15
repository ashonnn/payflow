import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import argon2
import jwt
from argon2.exceptions import InvalidHashError, VerificationError
from redis.asyncio import Redis

from payflow.core.clock import Clock


class PasswordHasher:
    def __init__(self, *, time_cost: int, memory_kib: int, parallelism: int) -> None:
        self._hasher = argon2.PasswordHasher(
            time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism
        )
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe())

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        return await asyncio.to_thread(self._verify, password_hash, password)

    async def verify_against_dummy(self, password: str) -> None:
        await self.verify(self._dummy_hash, password)

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerificationError, InvalidHashError:
            return False


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: UUID
    token_type: TokenType
    token_id: str
    expires_at: datetime


class TokenCodec:
    def __init__(self, secret: str, algorithm: str, clock: Clock) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._clock = clock

    def issue(
        self, subject: UUID, token_type: TokenType, ttl: timedelta
    ) -> tuple[str, TokenClaims]:
        issued_at = self._clock()
        claims = TokenClaims(
            subject=subject,
            token_type=token_type,
            token_id=secrets.token_urlsafe(16),
            expires_at=issued_at + ttl,
        )
        payload = {
            "sub": str(subject),
            "type": token_type.value,
            "jti": claims.token_id,
            "iat": issued_at,
            "exp": claims.expires_at,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return token, claims

    def decode(self, token: str, expected_type: TokenType) -> TokenClaims | None:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "type", "jti", "exp"]},
            )
            claims = TokenClaims(
                subject=UUID(payload["sub"]),
                token_type=TokenType(payload["type"]),
                token_id=str(payload["jti"]),
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except jwt.PyJWTError, ValueError:
            return None
        return claims if claims.token_type is expected_type else None


class RefreshTokenStore:
    """Allowlist of live refresh tokens; consuming one is atomic, so it rotates once."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def save(self, claims: TokenClaims) -> None:
        await self._redis.set(
            self._key(claims), str(claims.subject), exat=claims.expires_at
        )

    async def consume(self, claims: TokenClaims) -> bool:
        owner = await self._redis.getdel(self._key(claims))
        return owner == str(claims.subject)

    async def revoke(self, claims: TokenClaims) -> None:
        await self._redis.delete(self._key(claims))

    @staticmethod
    def _key(claims: TokenClaims) -> str:
        return f"refresh-token:{claims.token_id}"
