from dataclasses import dataclass
from uuid import UUID

from app.auth.security import PasswordService
from app.users.models import User, UserStatus
from app.users.repository import UsersRepository
from app.users.schemas import UserResponse
from app.users.service import DEFAULT_ROLE_DEFINITIONS

DEFAULT_DEMO_TENANT_ID = UUID("a1000000-0000-4000-8000-000000000001")


@dataclass(frozen=True, slots=True)
class DemoAccount:
    username: str
    email: str
    role_code: str


DEFAULT_DEMO_ACCOUNTS = (
    DemoAccount("demo-admin", "demo-admin@example.test", "admin"),
    DemoAccount("demo-user", "demo-user@example.test", "user"),
    DemoAccount("demo-cs", "demo-cs@example.test", "customer_service"),
    DemoAccount("demo-decision", "demo-decision@example.test", "decision_maker"),
)


class DemoTenantBootstrapper:
    def __init__(
        self,
        repository: UsersRepository,
        passwords: PasswordService,
    ) -> None:
        self._repository = repository
        self._passwords = passwords

    async def ensure(
        self,
        *,
        tenant_id: UUID,
        password: str,
        reset_password: bool = False,
    ) -> list[UserResponse]:
        if len(password) < 8:
            raise ValueError("演示账号密码至少需要 8 位。")

        roles = await self._repository.ensure_roles(
            tenant_id,
            DEFAULT_ROLE_DEFINITIONS,
        )
        roles_by_code = {role.code: role for role in roles}
        results: list[UserResponse] = []

        for account in DEFAULT_DEMO_ACCOUNTS:
            user = await self._repository.get_by_username(tenant_id, account.username)
            if user is None:
                user = User(
                    tenant_id=tenant_id,
                    username=account.username,
                    email=account.email,
                    password_hash=self._passwords.hash(password),
                    status=UserStatus.ACTIVE,
                    roles=[roles_by_code[account.role_code]],
                )
            else:
                user.email = account.email
                user.status = UserStatus.ACTIVE
                user.roles = [roles_by_code[account.role_code]]
                if reset_password:
                    user.password_hash = self._passwords.hash(password)

            await self._repository.save(user)
            results.append(UserResponse.from_entity(user))

        return results
