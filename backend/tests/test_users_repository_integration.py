from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.core.config import Settings
from app.db.session import Database
from app.users.models import Role, User, UserStatus
from app.users.repository import UsersRepository
from app.users.schemas import UserCreateRequest, UserUpdateRequest
from app.users.service import UserService

pytestmark = pytest.mark.integration


async def test_user_create_and_update_refreshes_server_managed_fields() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not configured")

    tenant_id = uuid4()
    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            service = UserService(UsersRepository(session), PasswordService())
            admin = await service.bootstrap_admin(
                tenant_id=tenant_id,
                username="integration-admin",
                email="integration-admin@example.test",
                password="integration-password",
            )

        principal = Principal(
            user_id=admin.id,
            tenant_id=tenant_id,
            username=admin.username,
            email=admin.email,
            roles=frozenset({"admin"}),
        )
        async with database.session_factory() as session:
            service = UserService(UsersRepository(session), PasswordService())
            created = await service.create_user(
                principal,
                UserCreateRequest(
                    username="integration-user",
                    email="integration-user@example.test",
                    password="integration-password",
                    role_codes={"user"},
                ),
            )

        async with database.session_factory() as session:
            service = UserService(UsersRepository(session), PasswordService())
            updated = await service.update_user(
                principal,
                created.id,
                UserUpdateRequest(status=UserStatus.DISABLED),
            )

        assert updated.status == UserStatus.DISABLED
        assert updated.updated_at >= updated.created_at
        assert updated.roles == ["user"]
    finally:
        async with database.session_factory() as session:
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Role).where(Role.tenant_id == tenant_id))
            await session.commit()
        await database.close()
