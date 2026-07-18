from uuid import UUID

from sqlalchemy import func, inspect as sqlalchemy_inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.documents.models import (
    KnowledgeDocument,
    KnowledgeSyncJob,
    KnowledgeSyncJobStatus,
)


class KnowledgeDocumentBusyRepositoryError(Exception):
    """A document already has a pending or processing synchronization job."""


class KnowledgeRepositoryError(Exception):
    """Knowledge ledger persistence failed after the session was rolled back."""


class KnowledgeDocumentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_upload(
        self,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> None:
        self._session.add_all([document, job])
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise KnowledgeRepositoryError from exc
        await self._session.refresh(document)
        await self._session.refresh(job)

    async def create_job(self, job: KnowledgeSyncJob) -> None:
        try:
            async with self._session.begin_nested():
                self._session.add(job)
                await self._session.flush()
            await self._session.commit()
        except IntegrityError as exc:
            raise KnowledgeDocumentBusyRepositoryError from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise KnowledgeRepositoryError from exc
        await self._session.refresh(job)

    async def save(
        self,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> None:
        document_state = self._column_state(document)
        job_state = self._column_state(job)
        self._session.add_all([document, job])
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            self._restore_column_state(document, document_state)
            self._restore_column_state(job, job_state)
            raise KnowledgeRepositoryError from exc
        await self._session.refresh(document)
        await self._session.refresh(job)

    @staticmethod
    def _column_state(entity) -> dict[str, object]:
        state = sqlalchemy_inspect(entity)
        return {
            key: value
            for key, value in state.dict.items()
            if key != "_sa_instance_state"
        }

    @staticmethod
    def _restore_column_state(entity, state: dict[str, object]) -> None:
        for key, value in state.items():
            setattr(entity, key, value)

    async def list_documents(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[KnowledgeDocument], int]:
        where = (
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
        statement = (
            select(KnowledgeDocument)
            .where(*where)
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_statement = select(func.count()).select_from(KnowledgeDocument).where(
            *where
        )
        items = list((await self._session.scalars(statement)).all())
        total = int(await self._session.scalar(count_statement) or 0)
        return items, total

    async def get_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.id == document_id,
        )
        if not include_deleted:
            statement = statement.where(KnowledgeDocument.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_job(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
    ) -> KnowledgeSyncJob | None:
        statement = select(KnowledgeSyncJob).where(
            KnowledgeSyncJob.tenant_id == tenant_id,
            KnowledgeSyncJob.id == job_id,
        )
        return await self._session.scalar(statement)

    async def get_active_job(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> KnowledgeSyncJob | None:
        statement = (
            select(KnowledgeSyncJob)
            .where(
                KnowledgeSyncJob.tenant_id == tenant_id,
                KnowledgeSyncJob.document_id == document_id,
                KnowledgeSyncJob.status.in_(
                    [
                        KnowledgeSyncJobStatus.PENDING,
                        KnowledgeSyncJobStatus.PROCESSING,
                    ]
                ),
            )
            .order_by(KnowledgeSyncJob.created_at.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)
