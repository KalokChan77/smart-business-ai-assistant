from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.core.config import Settings
from app.db.session import Database
from app.knowledge.documents.models import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSyncJob,
    KnowledgeSyncJobStatus,
    KnowledgeSyncOperation,
)
from app.knowledge.documents.repository import (
    KnowledgeDocumentBusyRepositoryError,
    KnowledgeDocumentsRepository,
)
from app.knowledge.documents.visibility import KnowledgeDocumentVisibilityPolicy
from app.knowledge.ports import KnowledgeRecord
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService

pytestmark = pytest.mark.integration


async def test_knowledge_document_repository_is_tenant_scoped_and_serializes_active_jobs() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not configured")

    tenant_a = uuid4()
    tenant_b = uuid4()
    suffix = uuid4().hex[:8]
    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username=f"knowledge-admin-a-{suffix}",
                email=f"knowledge-admin-a-{suffix}@example.test",
                password="integration-password",
            )
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"knowledge-admin-b-{suffix}",
                email=f"knowledge-admin-b-{suffix}@example.test",
                password="integration-password",
            )

        principal_a = Principal(
            user_id=admin_a.id,
            tenant_id=tenant_a,
            username=admin_a.username,
            email=admin_a.email,
            roles=frozenset({"admin"}),
        )
        principal_b = Principal(
            user_id=admin_b.id,
            tenant_id=tenant_b,
            username=admin_b.username,
            email=admin_b.email,
            roles=frozenset({"admin"}),
        )

        document = KnowledgeDocument(
            id=uuid4(),
            tenant_id=principal_a.tenant_id,
            uploaded_by_user_id=principal_a.user_id,
            original_filename="integration-rules.txt",
            storage_key=f"{principal_a.tenant_id}/{uuid4()}.txt",
            media_type="text/plain",
            extension="txt",
            size_bytes=17,
            sha256="c" * 64,
            status=KnowledgeDocumentStatus.PROCESSING,
            dify_document_id=str(uuid4()),
            dify_indexing_status="waiting",
        )
        upload_job = KnowledgeSyncJob(
            id=uuid4(),
            tenant_id=principal_a.tenant_id,
            document_id=document.id,
            created_by_user_id=principal_a.user_id,
            operation=KnowledgeSyncOperation.UPLOAD,
            status=KnowledgeSyncJobStatus.PROCESSING,
            dify_batch_id="integration-batch-upload",
            dify_indexing_status="waiting",
        )

        async with database.session_factory() as session:
            repository = KnowledgeDocumentsRepository(session)
            await repository.create_upload(document, upload_job)
            assert document.created_at is not None
            assert document.updated_at is not None
            assert upload_job.started_at is not None
            assert upload_job.created_at is not None

            items, total = await repository.list_documents(
                tenant_id=principal_a.tenant_id,
                limit=20,
                offset=0,
            )
            assert total == 1
            assert [item.id for item in items] == [document.id]
            assert (
                await repository.get_document(
                    tenant_id=principal_b.tenant_id,
                    document_id=document.id,
                )
                is None
            )
            assert (
                await repository.get_job(
                    tenant_id=principal_b.tenant_id,
                    job_id=upload_job.id,
                )
                is None
            )

            visibility = KnowledgeDocumentVisibilityPolicy(database)
            managed_record = KnowledgeRecord(
                document_id=document.dify_document_id or "",
                document_name=document.original_filename,
                content="tenant-managed",
                score=0.5,
            )
            shared_record = KnowledgeRecord(
                document_id=str(uuid4()),
                document_name="shared-preloaded.txt",
                content="shared",
                score=0.4,
            )
            assert await visibility.filter_visible(
                principal_a.tenant_id,
                (managed_record, shared_record),
            ) == (managed_record, shared_record)
            assert await visibility.filter_visible(
                principal_b.tenant_id,
                (managed_record, shared_record),
            ) == (shared_record,)

            conflicting = KnowledgeSyncJob(
                id=uuid4(),
                tenant_id=principal_a.tenant_id,
                document_id=document.id,
                created_by_user_id=principal_a.user_id,
                operation=KnowledgeSyncOperation.REINDEX,
                status=KnowledgeSyncJobStatus.PENDING,
            )
            with pytest.raises(KnowledgeDocumentBusyRepositoryError):
                await repository.create_job(conflicting)

            now = datetime.now(UTC)
            document.status = KnowledgeDocumentStatus.COMPLETED
            document.completed_at = now
            upload_job.status = KnowledgeSyncJobStatus.COMPLETED
            upload_job.completed_at = now
            await repository.save(document, upload_job)

            reindex_job = KnowledgeSyncJob(
                id=uuid4(),
                tenant_id=principal_a.tenant_id,
                document_id=document.id,
                created_by_user_id=principal_a.user_id,
                operation=KnowledgeSyncOperation.REINDEX,
                status=KnowledgeSyncJobStatus.PENDING,
            )
            await repository.create_job(reindex_job)
            active = await repository.get_active_job(
                tenant_id=principal_a.tenant_id,
                document_id=document.id,
            )
            assert active is not None and active.id == reindex_job.id

            reindex_job.status = KnowledgeSyncJobStatus.COMPLETED
            reindex_job.completed_at = datetime.now(UTC)
            document.status = KnowledgeDocumentStatus.DELETED
            document.deleted_at = datetime.now(UTC)
            await repository.save(document, reindex_job)

            _, remaining = await repository.list_documents(
                tenant_id=principal_a.tenant_id,
                limit=20,
                offset=0,
            )
            assert remaining == 0
            assert (
                await repository.get_document(
                    tenant_id=principal_a.tenant_id,
                    document_id=document.id,
                )
                is None
            )
            deleted = await repository.get_document(
                tenant_id=principal_a.tenant_id,
                document_id=document.id,
                include_deleted=True,
            )
            assert deleted is not None and deleted.status == KnowledgeDocumentStatus.DELETED
            assert await visibility.filter_visible(
                principal_a.tenant_id,
                (managed_record, shared_record),
            ) == (shared_record,)
    finally:
        async with database.session_factory() as session:
            await session.execute(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.tenant_id.in_([tenant_a, tenant_b])
                )
            )
            await session.execute(
                delete(User).where(User.tenant_id.in_([tenant_a, tenant_b]))
            )
            await session.execute(
                delete(Role).where(Role.tenant_id.in_([tenant_a, tenant_b]))
            )
            await session.commit()
        await database.close()
