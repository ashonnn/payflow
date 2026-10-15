from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.container import Container
from payflow.core.security import RefreshTokenStore
from payflow.db.models import User
from payflow.domain.exceptions import (
    AdminRequiredError,
    InvalidTokenError,
    RateLimitExceededError,
)
from payflow.domain.services.accounts import AccountService
from payflow.domain.services.auth import AuthService
from payflow.domain.services.deposits import DepositService
from payflow.domain.services.exchange import ExchangeService
from payflow.domain.services.history import HistoryService
from payflow.domain.services.reviews import ReviewService
from payflow.domain.services.transfers import TransferService


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_auth_service(session: SessionDep, container: ContainerDep) -> AuthService:
    settings = container.settings
    return AuthService(
        session,
        container.password_hasher,
        container.token_codec,
        RefreshTokenStore(container.redis),
        access_ttl=timedelta(seconds=settings.access_token_ttl_seconds),
        refresh_ttl=timedelta(seconds=settings.refresh_token_ttl_seconds),
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    auth: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise InvalidTokenError("missing bearer token")
    return await auth.authenticate(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_account_service(session: SessionDep) -> AccountService:
    return AccountService(session)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


def get_deposit_service(session: SessionDep, container: ContainerDep) -> DepositService:
    return DepositService(session, container.payment_provider, container.clock)


DepositServiceDep = Annotated[DepositService, Depends(get_deposit_service)]


def get_history_service(session: SessionDep) -> HistoryService:
    return HistoryService(session)


HistoryServiceDep = Annotated[HistoryService, Depends(get_history_service)]


def get_transfer_service(
    session: SessionDep, container: ContainerDep
) -> TransferService:
    return TransferService(session, container.fraud_policy, container.clock)


TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]


def get_exchange_service(
    session: SessionDep, container: ContainerDep
) -> ExchangeService:
    return ExchangeService(
        session, container.exchange_rates, container.settings.fx_spread, container.clock
    )


ExchangeServiceDep = Annotated[ExchangeService, Depends(get_exchange_service)]


def get_review_service(session: SessionDep, container: ContainerDep) -> ReviewService:
    return ReviewService(session, container.clock)


ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


def get_admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise AdminRequiredError
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]


async def limit_transfer_rate(user: CurrentUser, container: ContainerDep) -> None:
    decision = await container.transfer_rate_limiter.hit(str(user.id))
    if not decision.allowed:
        raise RateLimitExceededError(decision.retry_after_seconds)
