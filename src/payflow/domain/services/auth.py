from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from payflow.core.security import (
    PasswordHasher,
    RefreshTokenStore,
    TokenCodec,
    TokenType,
)
from payflow.db.models import User
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.users import UserRepository
from payflow.domain.exceptions import (
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    PhoneAlreadyRegisteredError,
)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    """Registration, credential checks and refresh token rotation."""

    def __init__(
        self,
        session: AsyncSession,
        hasher: PasswordHasher,
        codec: TokenCodec,
        refresh_tokens: RefreshTokenStore,
        *,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> None:
        self._users = UserRepository(session)
        self._accounts = AccountRepository(session)
        self._hasher = hasher
        self._codec = codec
        self._refresh_tokens = refresh_tokens
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    async def register(self, phone: str, password: str, full_name: str) -> User:
        """Create a user with an empty wallet per supported currency."""
        user = await self._users.create(
            phone=phone,
            full_name=full_name,
            password_hash=await self._hasher.hash(password),
        )
        if user is None:
            raise PhoneAlreadyRegisteredError
        await self._accounts.open_wallets(user.id)
        return user

    async def login(self, phone: str, password: str) -> TokenPair:
        user = await self._users.get_by_phone(phone)
        if user is None:
            # hash anyway so response time does not reveal which phones exist
            await self._hasher.verify_against_dummy(password)
            raise InvalidCredentialsError
        if not await self._hasher.verify(user.password_hash, password):
            raise InvalidCredentialsError
        self._ensure_active(user)
        return await self._issue_pair(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Exchange a refresh token for a new pair; each refresh token works once."""
        claims = self._codec.decode(refresh_token, TokenType.REFRESH)
        if claims is None or not await self._refresh_tokens.consume(claims):
            raise InvalidTokenError
        user = await self._users.get(claims.subject)
        if user is None:
            raise InvalidTokenError
        self._ensure_active(user)
        return await self._issue_pair(user)

    async def logout(self, refresh_token: str) -> None:
        claims = self._codec.decode(refresh_token, TokenType.REFRESH)
        if claims is not None:
            await self._refresh_tokens.revoke(claims)

    async def authenticate(self, access_token: str) -> User:
        claims = self._codec.decode(access_token, TokenType.ACCESS)
        if claims is None:
            raise InvalidTokenError
        user = await self._users.get(claims.subject)
        if user is None:
            raise InvalidTokenError
        self._ensure_active(user)
        return user

    async def _issue_pair(self, user: User) -> TokenPair:
        access_token, _ = self._codec.issue(user.id, TokenType.ACCESS, self._access_ttl)
        refresh_token, refresh_claims = self._codec.issue(
            user.id, TokenType.REFRESH, self._refresh_ttl
        )
        await self._refresh_tokens.save(refresh_claims)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(self._access_ttl.total_seconds()),
        )

    @staticmethod
    def _ensure_active(user: User) -> None:
        if not user.is_active:
            raise InactiveUserError
