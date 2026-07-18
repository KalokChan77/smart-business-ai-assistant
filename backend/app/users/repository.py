from collections.abc import Collection
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.users.models import Role, User


class DuplicateUserError(RuntimeError):
    """Raised when a tenant username or email unique constraint is violated."""


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, tenant_id: UUID, username: str) -> User | None:
        statement = (
            select(User)
            .options(selectinload(User.roles))
            .where(User.tenant_id == tenant_id, User.username == username)
        )
        return await self._session.scalar(statement)

    async def get_by_id(self, tenant_id: UUID, user_id: UUID) -> User | None:
        statement = (
            select(User)
            .options(selectinload(User.roles))
            .where(User.tenant_id == tenant_id, User.id == user_id)
        )
        return await self._session.scalar(statement)

    async def list_by_tenant(self, tenant_id: UUID) -> list[User]:
        statement = (
            select(User)
            .options(selectinload(User.roles))
            .where(User.tenant_id == tenant_id)
            .order_by(User.username)
        )
        result = await self._session.scalars(statement)
        return list(result.unique())

    async def count_by_tenant(self, tenant_id: UUID) -> int:
        statement = select(func.count(User.id)).where(User.tenant_id == tenant_id)
        return int(await self._session.scalar(statement) or 0)

    async def get_roles(self, tenant_id: UUID, codes: Collection[str]) -> list[Role]:
        if not codes:
            return []
        statement = select(Role).where(
            Role.tenant_id == tenant_id,
            Role.code.in_(set(codes)),
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def ensure_roles(
        self,
        tenant_id: UUID,
        role_definitions: Collection[tuple[str, str, str]],
    ) -> list[Role]:
        requested_codes = {code for code, _, _ in role_definitions}
        existing = await self.get_roles(tenant_id, requested_codes)
        existing_codes = {role.code for role in existing}
        created = [
            Role(
                tenant_id=tenant_id,
                code=code,
                name=name,
                description=description,
            )
            for code, name, description in role_definitions
            if code not in existing_codes
        ]
        self._session.add_all(created)
        if created:
            await self._session.flush()
        return [*existing, *created]

    async def save(self, user: User) -> None:
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateUserError("Tenant username or email already exists.") from exc
        await self._session.refresh(user)
        await self._session.refresh(user, attribute_names=["roles"])

    async def rollback(self) -> None:
        await self._session.rollback()
