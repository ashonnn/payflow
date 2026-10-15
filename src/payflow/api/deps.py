from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.container import Container
from payflow.core.security import RefreshTokenStore
from payflow.db.models import User
from payflow.domain.exceptions import InvalidTokenError
from payflow.domain.services.accounts import AccountService
from payflow.domain.services.auth import AuthService


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
