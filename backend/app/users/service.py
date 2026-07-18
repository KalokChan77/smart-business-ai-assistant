from uuid import UUID

from fastapi import status

from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.core.errors import AppError
from app.users.models import Role, User, UserStatus
from app.users.repository import DuplicateUserError, UsersRepository
from app.users.schemas import UserCreateRequest, UserResponse, UserUpdateRequest, validate_role_codes

ADMIN_ROLE = "admin"
DEFAULT_ROLE_DEFINITIONS = (
    ("admin", "管理员", "管理租户用户、角色和系统配置"),
    ("customer_service", "客服人员", "处理咨询、工单和 AI 推荐回复"),
    ("user", "企业用户", "使用 AI 对话和企业知识库"),
    ("decision_maker", "决策者", "查看分析统计和 AI 摘要"),
)


class UserService:
    def __init__(self, repository: UsersRepository, passwords: PasswordService) -> None:
        self._repository = repository
        self._passwords = passwords

    async def list_users(self, principal: Principal) -> list[UserResponse]:
        users = await self._repository.list_by_tenant(principal.tenant_id)
        return [UserResponse.from_entity(user) for user in users]

    async def create_user(
        self,
        principal: Principal,
        request: UserCreateRequest,
    ) -> UserResponse:
        role_codes = validate_role_codes(request.role_codes)
        if not role_codes:
            raise AppError(
                code="roles_required",
                message="用户至少需要一个角色。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        roles = await self._require_roles(principal.tenant_id, role_codes)
        user = User(
            tenant_id=principal.tenant_id,
            username=self._normalize_username(request.username),
            email=self._normalize_email(request.email),
            password_hash=self._passwords.hash(request.password.get_secret_value()),
            status=UserStatus.ACTIVE,
            roles=roles,
        )
        await self._save(user)
        return UserResponse.from_entity(user)

    async def update_user(
        self,
        principal: Principal,
        user_id: UUID,
        request: UserUpdateRequest,
    ) -> UserResponse:
        user = await self._repository.get_by_id(principal.tenant_id, user_id)
        if user is None:
            raise AppError(
                code="user_not_found",
                message="用户不存在。",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if request.email is not None:
            user.email = self._normalize_email(request.email)
        if request.status is not None:
            if user.id == principal.user_id and request.status == UserStatus.DISABLED:
                raise AppError(
                    code="cannot_disable_self",
                    message="管理员不能禁用自己的当前账户。",
                    status_code=status.HTTP_409_CONFLICT,
                )
            user.status = request.status
        if request.role_codes is not None:
            role_codes = validate_role_codes(request.role_codes)
            if not role_codes:
                raise AppError(
                    code="roles_required",
                    message="用户至少需要一个角色。",
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
            if user.id == principal.user_id and ADMIN_ROLE not in role_codes:
                raise AppError(
                    code="cannot_remove_own_admin_role",
                    message="管理员不能移除自己的管理员角色。",
                    status_code=status.HTTP_409_CONFLICT,
                )
            user.roles = await self._require_roles(principal.tenant_id, role_codes)

        await self._save(user)
        return UserResponse.from_entity(user)

    async def bootstrap_admin(
        self,
        *,
        tenant_id: UUID,
        username: str,
        email: str,
        password: str,
    ) -> UserResponse:
        if await self._repository.count_by_tenant(tenant_id) != 0:
            raise AppError(
                code="tenant_already_initialized",
                message="该租户已经存在用户，不能再次执行管理员初始化。",
                status_code=status.HTTP_409_CONFLICT,
            )
        roles = await self._repository.ensure_roles(tenant_id, DEFAULT_ROLE_DEFINITIONS)
        admin_role = next(role for role in roles if role.code == ADMIN_ROLE)
        user = User(
            tenant_id=tenant_id,
            username=self._normalize_username(username),
            email=self._normalize_email(email),
            password_hash=self._passwords.hash(password),
            status=UserStatus.ACTIVE,
            roles=[admin_role],
        )
        await self._save(user)
        return UserResponse.from_entity(user)

    async def _require_roles(
        self, tenant_id: UUID, role_codes: set[str]
    ) -> list[Role]:
        roles = await self._repository.get_roles(tenant_id, role_codes)
        found = {role.code for role in roles}
        missing = sorted(role_codes - found)
        if missing:
            raise AppError(
                code="unknown_roles",
                message="包含不存在的角色。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"role_codes": missing},
            )
        return roles

    async def _save(self, user: User) -> None:
        try:
            await self._repository.save(user)
        except DuplicateUserError as exc:
            raise AppError(
                code="user_conflict",
                message="用户名或邮箱已存在。",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().lower()

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()
