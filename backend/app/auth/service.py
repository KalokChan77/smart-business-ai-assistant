from uuid import UUID

from fastapi import status

from app.auth.principal import Principal
from app.auth.security import (
    IssuedTokenPair,
    JwtTokenService,
    PasswordService,
    TokenClaims,
    TokenType,
    TokenValidationError,
)
from app.auth.token_store import TokenRevocationStore, TokenStoreUnavailable
from app.core.errors import AppError
from app.users.models import User, UserStatus
from app.users.repository import UsersRepository


class AuthenticationService:
    def __init__(
        self,
        *,
        users: UsersRepository,
        passwords: PasswordService,
        tokens: JwtTokenService,
        revocations: TokenRevocationStore,
    ) -> None:
        self._users = users
        self._passwords = passwords
        self._tokens = tokens
        self._revocations = revocations

    async def login(
        self, tenant_id: UUID, username: str, password: str
    ) -> IssuedTokenPair:
        normalized_username = username.strip().lower()
        user = await self._users.get_by_username(tenant_id, normalized_username)
        if user is None:
            self._passwords.verify_dummy(password)
            raise self._invalid_credentials()

        is_valid, replacement_hash = self._passwords.verify_and_update(
            password,
            user.password_hash,
        )
        if not is_valid:
            raise self._invalid_credentials()
        self._ensure_active(user)

        if replacement_hash is not None:
            user.password_hash = replacement_hash
            await self._users.save(user)

        return self._tokens.issue_pair(self._to_principal(user))

    async def refresh(self, refresh_token: str) -> IssuedTokenPair:
        claims = self._decode(refresh_token, TokenType.REFRESH)
        if not await self._consume(claims):
            raise self._invalid_token()

        user = await self._users.get_by_id(claims.tenant_id, claims.subject)
        if user is None:
            raise self._invalid_token()
        self._ensure_active(user)

        return self._tokens.issue_pair(self._to_principal(user))

    async def authenticate_access_token(self, access_token: str) -> Principal:
        claims = self._decode(access_token, TokenType.ACCESS)
        if await self._is_revoked(claims.jti):
            raise self._invalid_token()

        user = await self._users.get_by_id(claims.tenant_id, claims.subject)
        if user is None:
            raise self._invalid_token()
        self._ensure_active(user)
        return self._to_principal(user)

    async def logout(self, access_token: str, refresh_token: str) -> None:
        access_claims = self._decode(access_token, TokenType.ACCESS)
        refresh_claims = self._decode(refresh_token, TokenType.REFRESH)
        if (
            access_claims.subject != refresh_claims.subject
            or access_claims.tenant_id != refresh_claims.tenant_id
        ):
            raise self._invalid_token()
        await self._revoke(access_claims)
        await self._revoke(refresh_claims)

    def _decode(self, token: str, expected_type: TokenType) -> TokenClaims:
        try:
            return self._tokens.decode(token, expected_type=expected_type)
        except TokenValidationError as exc:
            raise self._invalid_token() from exc

    async def _is_revoked(self, jti: str) -> bool:
        try:
            return await self._revocations.is_revoked(jti)
        except TokenStoreUnavailable as exc:
            raise self._auth_unavailable() from exc

    async def _consume(self, claims: TokenClaims) -> bool:
        try:
            return await self._revocations.consume(claims.jti, claims.expires_at)
        except TokenStoreUnavailable as exc:
            raise self._auth_unavailable() from exc

    async def _revoke(self, claims: TokenClaims) -> None:
        try:
            await self._revocations.revoke(claims.jti, claims.expires_at)
        except TokenStoreUnavailable as exc:
            raise self._auth_unavailable() from exc

    @staticmethod
    def _to_principal(user: User) -> Principal:
        return Principal(
            user_id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            email=user.email,
            roles=frozenset(role.code for role in user.roles),
        )

    @staticmethod
    def _ensure_active(user: User) -> None:
        if user.status != UserStatus.ACTIVE:
            raise AppError(
                code="user_disabled",
                message="用户账户已被禁用。",
                status_code=status.HTTP_403_FORBIDDEN,
            )

    @staticmethod
    def _invalid_credentials() -> AppError:
        return AppError(
            code="invalid_credentials",
            message="用户名或密码错误。",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    def _invalid_token() -> AppError:
        return AppError(
            code="invalid_token",
            message="访问令牌无效或已过期。",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    def _auth_unavailable() -> AppError:
        return AppError(
            code="authentication_unavailable",
            message="认证服务暂时不可用。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
