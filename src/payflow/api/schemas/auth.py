from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from payflow.api.schemas.common import PhoneNumber


class RegisterRequest(BaseModel):
    phone: PhoneNumber
    password: SecretStr = Field(min_length=8, max_length=128)
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]


class LoginRequest(BaseModel):
    phone: PhoneNumber
    password: SecretStr = Field(max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone: str
    full_name: str
    is_admin: bool
    created_at: datetime
