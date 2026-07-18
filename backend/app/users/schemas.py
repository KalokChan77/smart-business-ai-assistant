from datetime import datetime
import re
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from app.users.models import User, UserStatus

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_USERNAME_PATTERN = r"^[A-Za-z0-9._-]+$"
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def validate_role_codes(role_codes: set[str]) -> set[str]:
    invalid = sorted(code for code in role_codes if _ROLE_PATTERN.fullmatch(code) is None)
    if invalid:
        raise ValueError(f"Invalid role codes: {', '.join(invalid)}")
    return role_codes


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=_USERNAME_PATTERN)
    email: str = Field(min_length=3, max_length=255, pattern=_EMAIL_PATTERN)
    password: SecretStr = Field(min_length=8, max_length=128)
    role_codes: set[str] = Field(default_factory=lambda: {"user"})

    @field_validator("username", "email", mode="before")
    @classmethod
    def strip_identity_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("role_codes", mode="before")
    @classmethod
    def normalize_roles(cls, value: object) -> object:
        if isinstance(value, (list, set, tuple)):
            return {str(item).strip().lower() for item in value}
        return value

    @field_validator("role_codes")
    @classmethod
    def validate_roles(cls, value: set[str]) -> set[str]:
        return validate_role_codes(value)


class UserUpdateRequest(BaseModel):
    email: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=_EMAIL_PATTERN,
    )
    status: UserStatus | None = None
    role_codes: set[str] | None = None

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("role_codes", mode="before")
    @classmethod
    def normalize_roles(cls, value: object) -> object:
        if isinstance(value, (list, set, tuple)):
            return {str(item).strip().lower() for item in value}
        return value

    @field_validator("role_codes")
    @classmethod
    def validate_roles(cls, value: set[str] | None) -> set[str] | None:
        return validate_role_codes(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdateRequest":
        if self.email is None and self.status is None and self.role_codes is None:
            raise ValueError("At least one user field must be provided.")
        return self


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    username: str
    email: str
    status: UserStatus
    roles: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            email=user.email,
            status=user.status,
            roles=sorted(role.code for role in user.roles),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

