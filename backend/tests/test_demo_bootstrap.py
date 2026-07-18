from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.auth.security import PasswordService
from app.users.demo_bootstrap import DemoTenantBootstrapper
from app.users.models import Role, User
from app.users.repository import DuplicateUserError
from app.users.service import DEFAULT_ROLE_DEFINITIONS


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

    async def get_by_username(self, tenant_id: UUID, username: str) -> User | None:
        return next(
            (
                user
                for user in self.users.values()
                if user.tenant_id == tenant_id and user.username == username
            ),
            None,
        )

    async def ensure_roles(self, tenant_id: UUID, role_definitions) -> list[Role]:
        assert tenant_id == self.tenant_id
        assert tuple(role_definitions) == DEFAULT_ROLE_DEFINITIONS
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


async def test_demo_bootstrap_is_idempotent_and_can_reset_password() -> None:
    tenant_id = uuid4()
    repository = FakeUsersRepository(tenant_id)
    passwords = PasswordService()
    bootstrapper = DemoTenantBootstrapper(repository, passwords)

    first = await bootstrapper.ensure(
        tenant_id=tenant_id,
        password="demo-password",
    )
    assert sorted(user.username for user in first) == [
        "demo-admin",
        "demo-cs",
        "demo-decision",
        "demo-user",
    ]
    assert {tuple(user.roles) for user in first} == {
        ("admin",),
        ("customer_service",),
        ("decision_maker",),
        ("user",),
    }

    second = await bootstrapper.ensure(
        tenant_id=tenant_id,
        password="changed-password",
        reset_password=False,
    )
    assert len(second) == 4
    admin = next(user for user in repository.users.values() if user.username == "demo-admin")
    still_valid, _ = passwords.verify_and_update("demo-password", admin.password_hash)
    assert still_valid is True

    await bootstrapper.ensure(
        tenant_id=tenant_id,
        password="changed-password",
        reset_password=True,
    )
    reset_valid, _ = passwords.verify_and_update("changed-password", admin.password_hash)
    assert reset_valid is True
    old_valid, _ = passwords.verify_and_update("demo-password", admin.password_hash)
    assert old_valid is False


async def test_demo_bootstrap_rejects_short_password() -> None:
    tenant_id = uuid4()
    bootstrapper = DemoTenantBootstrapper(
        FakeUsersRepository(tenant_id),
        PasswordService(),
    )

    with pytest.raises(ValueError, match="至少需要 8 位"):
        await bootstrapper.ensure(tenant_id=tenant_id, password="short")
