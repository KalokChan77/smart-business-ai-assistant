from uuid import UUID

from sqlalchemy import select

from app.db.session import Database
from app.knowledge.documents.models import KnowledgeDocument
from app.knowledge.ports import KnowledgeRecord


class KnowledgeVisibilityUnavailableError(Exception):
    """Managed-document tenant visibility could not be evaluated safely."""


class KnowledgeDocumentVisibilityPolicy:
    """Keep preloaded shared documents visible and isolate FastAPI-managed uploads."""

    def __init__(self, database: Database | None) -> None:
        self._database = database

    async def filter_visible(
        self,
        tenant_id: UUID,
        records: tuple[KnowledgeRecord, ...],
    ) -> tuple[KnowledgeRecord, ...]:
        if not records:
            return records
        if self._database is None:
            raise KnowledgeVisibilityUnavailableError(
                "Knowledge visibility database is unavailable."
            )

        document_ids = {record.document_id for record in records}
        async with self._database.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeDocument.dify_document_id,
                        KnowledgeDocument.tenant_id,
                        KnowledgeDocument.deleted_at,
                    ).where(KnowledgeDocument.dify_document_id.in_(document_ids))
                )
            ).all()

        managed = {
            document_id: (owner_tenant_id, deleted_at)
            for document_id, owner_tenant_id, deleted_at in rows
            if document_id is not None
        }
        visible_ids = {
            document_id
            for document_id in document_ids
            if document_id not in managed
            or (
                managed[document_id][0] == tenant_id
                and managed[document_id][1] is None
            )
        }
        return tuple(
            record for record in records if record.document_id in visible_ids
        )
