from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.core.errors import AppError
from app.users.models import Role, User, UserStatus
from app.users.repository import DuplicateUserError
from app.users.schemas import UserCreateRequest, UserUpdateRequest
from app.users.service import DEFAULT_ROLE_DEFINITIONS, UserService


class FakeUsersRepository:
    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.users: dict[UUID, User] = {}
        self.roles = {
            code: Role(
                id=uuid4(),
                tenant_id=tenant_id,
                code=code,
                name=name,
                description=description,
            )
            for code, name, description in DEFAULT_ROLE_DEFINITIONS
        }

    async def list_by_tenant(self, tenant_id: UUID) -> list[User]:
        return sorted(
            (user for user in self.users.values() if user.tenant_id == tenant_id),
            key=lambda user: user.username,
        )

    async def get_by_id(self, tenant_id: UUID, user_id: UUID) -> User | None:
        user = self.users.get(user_id)
        return user if user is not None and user.tenant_id == tenant_id else None

    async def count_by_tenant(self, tenant_id: UUID) -> int:
        return sum(user.tenant_id == tenant_id for user in self.users.values())

    async def get_roles(self, tenant_id: UUID, codes: set[str]) -> list[Role]:
        if tenant_id != self.tenant_id:
            return []
        return [self.roles[code] for code in codes if code in self.roles]

    async def ensure_roles(self, tenant_id: UUID, role_definitions) -> list[Role]:
        assert tenant_id == self.tenant_id
        return list(self.roles.values())

    async def save(self, user: User) -> None:
        for existing in self.users.values():
            if existing.id != user.id and existing.tenant_id == user.tenant_id:
                if existing.username == user.username or existing.email == user.email:
                    raise DuplicateUserError()
        if user.id is None:
            user.id = uuid4()
        now = datetime.now(UTC)
        if user.created_at is None:
            user.created_at = now
        user.updated_at = now
        self.users[user.id] = user


def admin_principal(tenant_id: UUID, *, user_id: UUID | None = None) -> Principal:
    return Principal(
        user_id=user_id or uuid4(),
        tenant_id=tenant_id,
        username="admin",
        email="admin@example.com",
        roles=frozenset({"admin"}),
    )


async def test_create_user_normalizes_identity_hashes_password_and_assigns_roles() -> None:
    tenant_id = uuid4()
    repository = FakeUsersRepository(tenant_id)
    passwords = PasswordService()
    service = UserService(repository, passwords)

    created = await service.create_user(
        admin_principal(tenant_id),
        UserCreateRequest(
            username=" Alice ",
            email=" ALICE@EXAMPLE.COM ",
            password="correct-password",
            role_codes={"user", "customer_service"},
        ),
    )

    entity = repository.users[created.id]
    valid, _ = passwords.verify_and_update("correct-password", entity.password_hash)
    assert created.username == "alice"
    assert created.email == "alice@example.com"
    assert created.roles == ["customer_service", "user"]
    assert valid is True
    assert entity.password_hash != "correct-password"


async def test_create_user_rejects_unknown_or_empty_roles() -> None:
    tenant_id = uuid4()
    service = UserService(FakeUsersRepository(tenant_id), PasswordService())
    principal = admin_principal(tenant_id)

    with pytest.raises(AppError) as unknown:
        await service.create_user(
            principal,
            UserCreateRequest(
                username="alice",
                email="alice@example.com",
                password="correct-password",
                role_codes={"missing_role"},
            ),
        )
    assert unknown.value.code == "unknown_roles"

    with pytest.raises(AppError) as empty:
        await service.create_user(
            principal,
            UserCreateRequest(
                username="bob",
                email="bob@example.com",
                password="correct-password",
                role_codes=set(),
            ),
        )
    assert empty.value.code == "roles_required"


async def test_admin_cannot_disable_or_remove_own_admin_role() -> None:
    tenant_id = uuid4()
    repository = FakeUsersRepository(tenant_id)
    passwords = PasswordService()
    service = UserService(repository, passwords)
    principal = admin_principal(tenant_id)
    admin = User(
        id=principal.user_id,
        tenant_id=tenant_id,
        username="admin",
        email="admin@example.com",
        password_hash=passwords.hash("correct-password"),
        roles=[repository.roles["admin"]],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    repository.users[admin.id] = admin

    with pytest.raises(AppError) as disabled:
        await service.update_user(
            principal,
            admin.id,
            UserUpdateRequest(status=UserStatus.DISABLED),
        )
    assert disabled.value.code == "cannot_disable_self"

    with pytest.raises(AppError) as role_removed:
        await service.update_user(
            principal,
            admin.id,
            UserUpdateRequest(role_codes={"user"}),
        )
    assert role_removed.value.code == "cannot_remove_own_admin_role"


async def test_user_lookup_is_tenant_scoped() -> None:
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    repository = FakeUsersRepository(tenant_id)
    service = UserService(repository, PasswordService())

    with pytest.raises(AppError) as captured:
        await service.update_user(
            admin_principal(other_tenant_id),
            uuid4(),
            UserUpdateRequest(email="updated@example.com"),
        )

    assert captured.value.code == "user_not_found"


async def test_bootstrap_admin_only_runs_for_empty_tenant() -> None:
    tenant_id = uuid4()
    repository = FakeUsersRepository(tenant_id)
    service = UserService(repository, PasswordService())

    created = await service.bootstrap_admin(
        tenant_id=tenant_id,
        username="Admin",
        email="ADMIN@example.com",
        password="correct-password",
    )

    assert created.username == "admin"
    assert created.roles == ["admin"]
    with pytest.raises(AppError) as captured:
        await service.bootstrap_admin(
            tenant_id=tenant_id,
            username="second",
            email="second@example.com",
            password="correct-password",
        )
    assert captured.value.code == "tenant_already_initialized"


