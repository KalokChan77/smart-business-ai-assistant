from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class LoginRequest(BaseModel):
    tenant_id: UUID
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: SecretStr = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: SecretStr = Field(min_length=1)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    username: str
    email: str
    roles: list[str]
