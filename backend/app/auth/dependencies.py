from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService
from app.auth.service import AuthenticationService
from app.auth.token_store import RedisTokenRevocationStore
from app.core.errors import AppError
from app.db.dependencies import get_db_session
from app.users.repository import UsersRepository

_bearer = HTTPBearer(auto_error=False)
_password_service = PasswordService()


def get_password_service() -> PasswordService:
    return _password_service


def get_users_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UsersRepository:
    return UsersRepository(session)


def get_token_service(request: Request) -> JwtTokenService:
    settings = request.app.state.settings
    if settings.jwt_secret_key is None:
        raise AppError(
            code="authentication_not_configured",
            message="认证服务尚未配置。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    secret = settings.jwt_secret_key.get_secret_value()
    if len(secret) < 32:
        raise AppError(
            code="authentication_not_configured",
            message="认证服务配置不符合安全要求。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return JwtTokenService(
        secret=secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_ttl=timedelta(minutes=settings.jwt_access_ttl_minutes),
        refresh_ttl=timedelta(days=settings.jwt_refresh_ttl_days),
    )


def get_authentication_service(
    request: Request,
    users: Annotated[UsersRepository, Depends(get_users_repository)],
    passwords: Annotated[PasswordService, Depends(get_password_service)],
    tokens: Annotated[JwtTokenService, Depends(get_token_service)],
) -> AuthenticationService:
    runtime = request.app.state.runtime
    if runtime is None or runtime.redis is None:
        raise AppError(
            code="authentication_unavailable",
            message="认证服务暂时不可用。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return AuthenticationService(
        users=users,
        passwords=passwords,
        tokens=tokens,
        revocations=RedisTokenRevocationStore(runtime.redis),
    )


class AccessSession:
    __slots__ = ("access_token", "principal")

    def __init__(self, access_token: str, principal: Principal) -> None:
        self.access_token = access_token
        self.principal = principal


async def get_access_session(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AccessSession:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="not_authenticated",
            message="请先登录。",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = await service.authenticate_access_token(credentials.credentials)
    return AccessSession(credentials.credentials, principal)


async def get_current_principal(
    session: Annotated[AccessSession, Depends(get_access_session)],
) -> Principal:
    return session.principal


def require_any_role(*roles: str) -> Callable:
    required = frozenset(roles)

    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if principal.roles.isdisjoint(required):
            raise AppError(
                code="forbidden",
                message="当前用户没有执行此操作的权限。",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return principal

    return dependency
