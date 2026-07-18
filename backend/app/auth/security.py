from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError as PyJWTInvalidTokenError
from pwdlib import PasswordHash

from app.auth.principal import Principal


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenValidationError(ValueError):
    """Raised when a JWT is invalid, expired or used for the wrong purpose."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: UUID
    tenant_id: UUID
    token_type: TokenType
    jti: str
    roles: frozenset[str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedTokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int


class PasswordService:
    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash(uuid4().hex)

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify_and_update(self, password: str, password_hash: str) -> tuple[bool, str | None]:
        return self._password_hash.verify_and_update(password, password_hash)

    def verify_dummy(self, password: str) -> None:
        self._password_hash.verify(password, self._dummy_hash)


class JwtTokenService:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        issuer: str,
        audience: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    def issue_pair(self, principal: Principal) -> IssuedTokenPair:
        access_token = self._encode(principal, TokenType.ACCESS, self._access_ttl)
        refresh_token = self._encode(principal, TokenType.REFRESH, self._refresh_ttl)
        return IssuedTokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=int(self._access_ttl.total_seconds()),
        )

    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": [
                        "sub",
                        "tenant_id",
                        "type",
                        "jti",
                        "iat",
                        "exp",
                        "iss",
                        "aud",
                    ]
                },
            )
            token_type = TokenType(payload["type"])
            if token_type != expected_type:
                raise TokenValidationError("JWT token type does not match endpoint usage.")
            jti = payload["jti"]
            if not isinstance(jti, str) or not jti:
                raise TokenValidationError("JWT jti is invalid.")
            roles = payload.get("roles", [])
            if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
                raise TokenValidationError("JWT roles claim is invalid.")
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
            return TokenClaims(
                subject=UUID(payload["sub"]),
                tenant_id=UUID(payload["tenant_id"]),
                token_type=token_type,
                jti=jti,
                roles=frozenset(roles),
                expires_at=expires_at,
            )
        except (PyJWTInvalidTokenError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TokenValidationError):
                raise
            raise TokenValidationError("JWT validation failed.") from exc

    def _encode(
        self,
        principal: Principal,
        token_type: TokenType,
        ttl: timedelta,
    ) -> str:
        issued_at = datetime.now(UTC)
        expires_at = issued_at + ttl
        payload = {
            "sub": str(principal.user_id),
            "tenant_id": str(principal.tenant_id),
            "username": principal.username,
            "roles": sorted(principal.roles),
            "type": token_type.value,
            "jti": uuid4().hex,
            "iat": issued_at,
            "exp": expires_at,
            "iss": self._issuer,
            "aud": self._audience,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)
