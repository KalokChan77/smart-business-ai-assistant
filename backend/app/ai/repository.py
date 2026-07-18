from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIRun


class DuplicateAIRunError(Exception):
    """Raised when the same owner reuses an AI request ID."""


class AIRunsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: AIRun) -> None:
        self._session.add(run)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateAIRunError from exc
        await self._session.refresh(run)

    async def save(self, run: AIRun) -> None:
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)

    async def get_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        run_id: UUID,
    ) -> AIRun | None:
        statement = select(AIRun).where(
            AIRun.id == run_id,
            AIRun.tenant_id == tenant_id,
            AIRun.user_id == user_id,
        )
        return await self._session.scalar(statement)

    async def get_by_request_id(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        request_id: str,
    ) -> AIRun | None:
        statement = select(AIRun).where(
            AIRun.tenant_id == tenant_id,
            AIRun.user_id == user_id,
            AIRun.request_id == request_id,
        )
        return await self._session.scalar(statement)
