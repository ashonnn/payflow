from fastapi import APIRouter, status

from payflow.api.deps import AuthServiceDep, CurrentUser, SessionDep
from payflow.api.routes import API_PREFIX
from payflow.api.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix=API_PREFIX, tags=["auth"])


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, auth: AuthServiceDep, session: SessionDep
) -> UserResponse:
    user = await auth.register(
        payload.phone, payload.password.get_secret_value(), payload.full_name
    )
    await session.commit()
    return UserResponse.model_validate(user)


@router.post("/auth/login")
async def login(payload: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    tokens = await auth.login(payload.phone, payload.password.get_secret_value())
    return TokenResponse.model_validate(tokens)


@router.post("/auth/refresh")
async def refresh(payload: RefreshRequest, auth: AuthServiceDep) -> TokenResponse:
    tokens = await auth.refresh(payload.refresh_token)
    return TokenResponse.model_validate(tokens)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, auth: AuthServiceDep) -> None:
    await auth.logout(payload.refresh_token)


@router.get("/me")
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
