from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.auth.service import AuthenticationService
from app.core.errors import AppError
from app.users.models import Role, User, UserStatus


class FakeUsersRepository:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.save_count = 0

    async def get_by_username(self, tenant_id: UUID, username: str) -> User | None:
        if self.user is None:
            return None
        if self.user.tenant_id == tenant_id and self.user.username == username:
            return self.user
        return None

    async def get_by_id(self, tenant_id: UUID, user_id: UUID) -> User | None:
        if self.user is None:
            return None
        if self.user.tenant_id == tenant_id and self.user.id == user_id:
            return self.user
        return None

    async def save(self, user: User) -> None:
        self.user = user
        self.save_count += 1


class InMemoryRevocations:
    def __init__(self) -> None:
        self.revoked: set[str] = set()

    async def revoke(self, jti: str, expires_at: datetime) -> None:
        self.revoked.add(jti)

    async def consume(self, jti: str, expires_at: datetime) -> bool:
        if jti in self.revoked:
            return False
        self.revoked.add(jti)
        return True

    async def is_revoked(self, jti: str) -> bool:
        return jti in self.revoked


def make_user(passwords: PasswordService) -> User:
    tenant_id = uuid4()
    role = Role(
        id=uuid4(),
        tenant_id=tenant_id,
        code="admin",
        name="管理员",
        description="test",
    )
    return User(
        id=uuid4(),
        tenant_id=tenant_id,
        username="admin",
        email="admin@example.com",
        password_hash=passwords.hash("correct-password"),
        status=UserStatus.ACTIVE,
        roles=[role],
    )


def build_service(user: User | None = None):
    passwords = PasswordService()
    user = user or make_user(passwords)
    repository = FakeUsersRepository(user)
    tokens = JwtTokenService(
        secret="test-secret-that-is-longer-than-32-bytes",
        algorithm="HS256",
        issuer="test-issuer",
        audience="test-audience",
        access_ttl=timedelta(minutes=30),
        refresh_ttl=timedelta(days=7),
    )
    revocations = InMemoryRevocations()
    service = AuthenticationService(
        users=repository,
        passwords=passwords,
        tokens=tokens,
        revocations=revocations,
    )
    return service, repository, tokens, revocations, user


async def test_login_and_access_authentication_succeed() -> None:
    service, _, _, _, user = build_service()

    pair = await service.login(user.tenant_id, " ADMIN ", "correct-password")
    current = await service.authenticate_access_token(pair.access_token)

    assert current.user_id == user.id
    assert current.roles == frozenset({"admin"})


async def test_invalid_password_uses_stable_authentication_error() -> None:
    service, _, _, _, user = build_service()

    with pytest.raises(AppError) as captured:
        await service.login(user.tenant_id, user.username, "wrong-password")

    assert captured.value.code == "invalid_credentials"
    assert captured.value.status_code == 401


async def test_refresh_token_is_rotated_and_cannot_be_replayed() -> None:
    service, _, tokens, revocations, user = build_service()
    pair = await service.login(user.tenant_id, user.username, "correct-password")
    old_claims = tokens.decode(pair.refresh_token, expected_type=TokenType.REFRESH)

    rotated = await service.refresh(pair.refresh_token)

    assert rotated.refresh_token != pair.refresh_token
    assert old_claims.jti in revocations.revoked
    with pytest.raises(AppError) as captured:
        await service.refresh(pair.refresh_token)
    assert captured.value.code == "invalid_token"


async def test_logout_revokes_access_and_refresh_tokens() -> None:
    service, _, tokens, revocations, user = build_service()
    pair = await service.login(user.tenant_id, user.username, "correct-password")
    access_claims = tokens.decode(pair.access_token, expected_type=TokenType.ACCESS)
    refresh_claims = tokens.decode(pair.refresh_token, expected_type=TokenType.REFRESH)

    await service.logout(pair.access_token, pair.refresh_token)

    assert {access_claims.jti, refresh_claims.jti} <= revocations.revoked
    with pytest.raises(AppError) as captured:
        await service.authenticate_access_token(pair.access_token)
    assert captured.value.code == "invalid_token"


async def test_database_roles_and_status_override_jwt_snapshot() -> None:
    service, _, _, _, user = build_service()
    pair = await service.login(user.tenant_id, user.username, "correct-password")
    user.roles = [
        Role(
            id=uuid4(),
            tenant_id=user.tenant_id,
            code="user",
            name="企业用户",
            description="test",
        )
    ]

    current = await service.authenticate_access_token(pair.access_token)
    assert current.roles == frozenset({"user"})

    user.status = UserStatus.DISABLED
    with pytest.raises(AppError) as captured:
        await service.authenticate_access_token(pair.access_token)
    assert captured.value.code == "user_disabled"
