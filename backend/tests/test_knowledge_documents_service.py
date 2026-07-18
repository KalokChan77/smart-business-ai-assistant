from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyNotFoundError,
    DifyProtocolError,
    DifyTimeoutError,
)
from app.ai.dify.schemas import (
    DifyDocumentIndexingStatus,
    DifyDocumentMutationResult,
)
from app.auth.principal import Principal
from app.core.errors import AppError
from app.knowledge.documents.models import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSyncJob,
    KnowledgeSyncJobStatus,
    KnowledgeSyncOperation,
)
from app.knowledge.documents.repository import (
    KnowledgeDocumentBusyRepositoryError,
    KnowledgeRepositoryError,
)
from app.knowledge.documents.service import KnowledgeDocumentsService
from app.knowledge.documents.storage import (
    KnowledgeStorageError,
    KnowledgeStoredFileMissingError,
)
from app.knowledge.documents.validation import (
    KnowledgeFileInvalidError,
    KnowledgeFileTooLargeError,
    KnowledgeFileTypeNotSupportedError,
    ValidatedKnowledgeFile,
)


class FakeRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, KnowledgeDocument] = {}
        self.jobs: dict[UUID, KnowledgeSyncJob] = {}
        self.save_failures_remaining = 0

    async def create_upload(
        self,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> None:
        self._stamp_document(document)
        self._stamp_job(job)
        self.documents[document.id] = document
        self.jobs[job.id] = job

    async def create_job(self, job: KnowledgeSyncJob) -> None:
        if any(
            item.document_id == job.document_id
            and item.status
            in {KnowledgeSyncJobStatus.PENDING, KnowledgeSyncJobStatus.PROCESSING}
            for item in self.jobs.values()
        ):
            raise KnowledgeDocumentBusyRepositoryError
        self._stamp_job(job)
        self.jobs[job.id] = job

    async def save(
        self,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> None:
        if self.save_failures_remaining:
            self.save_failures_remaining -= 1
            raise KnowledgeRepositoryError
        now = datetime.now(UTC)
        document.updated_at = now
        job.updated_at = now
        self.documents[document.id] = document
        self.jobs[job.id] = job

    async def list_documents(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[KnowledgeDocument], int]:
        items = sorted(
            (
                item
                for item in self.documents.values()
                if item.tenant_id == tenant_id and item.deleted_at is None
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return items[offset : offset + limit], len(items)

    async def get_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> KnowledgeDocument | None:
        del for_update
        document = self.documents.get(document_id)
        if document is None or document.tenant_id != tenant_id:
            return None
        if not include_deleted and document.deleted_at is not None:
            return None
        return document

    async def get_job(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
    ) -> KnowledgeSyncJob | None:
        job = self.jobs.get(job_id)
        if job is None or job.tenant_id != tenant_id:
            return None
        return job

    async def get_active_job(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> KnowledgeSyncJob | None:
        return next(
            (
                item
                for item in self.jobs.values()
                if item.tenant_id == tenant_id
                and item.document_id == document_id
                and item.status
                in {
                    KnowledgeSyncJobStatus.PENDING,
                    KnowledgeSyncJobStatus.PROCESSING,
                }
            ),
            None,
        )

    @staticmethod
    def _stamp_document(document: KnowledgeDocument) -> None:
        now = datetime.now(UTC)
        document.created_at = now
        document.updated_at = now

    @staticmethod
    def _stamp_job(job: KnowledgeSyncJob) -> None:
        now = datetime.now(UTC)
        job.started_at = now
        job.created_at = now
        job.updated_at = now


class FakeValidator:
    def __init__(
        self,
        result: ValidatedKnowledgeFile | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or ValidatedKnowledgeFile(
            filename="rules.txt",
            extension="txt",
            media_type="text/plain",
            content="教学规则".encode(),
            size_bytes=len("教学规则".encode()),
            sha256="a" * 64,
        )
        self.error = error

    async def read_and_validate(self, upload: UploadFile) -> ValidatedKnowledgeFile:
        del upload
        if self.error is not None:
            raise self.error
        return self.result


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.fail_save = False
        self.fail_read = False
        self.fail_delete = False

    async def save(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        extension: str,
        content: bytes,
    ) -> str:
        if self.fail_save:
            raise KnowledgeStorageError("sensitive storage detail")
        key = f"{tenant_id}/{document_id}.{extension}"
        self.files[key] = content
        return key

    async def read(self, storage_key: str) -> bytes:
        if self.fail_read:
            raise KnowledgeStorageError("sensitive storage detail")
        if storage_key not in self.files:
            raise KnowledgeStoredFileMissingError("missing")
        return self.files[storage_key]

    async def delete(self, storage_key: str) -> None:
        if self.fail_delete:
            raise KnowledgeStorageError("sensitive storage detail")
        self.files.pop(storage_key, None)


class FakeDifyClient:
    def __init__(self) -> None:
        self.mutation_result = DifyDocumentMutationResult(
            document_id=str(uuid4()),
            indexing_status="waiting",
            batch="batch-test",
        )
        self.indexing_statuses: tuple[DifyDocumentIndexingStatus, ...] = ()
        self.create_error: Exception | None = None
        self.update_error: Exception | None = None
        self.status_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.created_files: list[tuple[str, str, bytes]] = []
        self.updated_files: list[tuple[str, str, str, bytes]] = []
        self.deleted_documents: list[str] = []

    async def create_document_by_file(
        self,
        *,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> DifyDocumentMutationResult:
        if self.create_error is not None:
            raise self.create_error
        self.created_files.append((filename, media_type, content))
        return self.mutation_result

    async def update_document_by_file(
        self,
        *,
        document_id: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> DifyDocumentMutationResult:
        if self.update_error is not None:
            raise self.update_error
        self.updated_files.append((document_id, filename, media_type, content))
        return self.mutation_result

    async def get_document_indexing_status(
        self,
        *,
        batch: str,
    ) -> tuple[DifyDocumentIndexingStatus, ...]:
        del batch
        if self.status_error is not None:
            raise self.status_error
        return self.indexing_statuses

    async def delete_document(self, *, document_id: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted_documents.append(document_id)


class FakeFactory:
    def __init__(
        self,
        client: FakeDifyClient,
        open_error: Exception | None = None,
    ) -> None:
        self.client = client
        self.open_error = open_error

    @asynccontextmanager
    async def open(self) -> AsyncIterator[FakeDifyClient]:
        if self.open_error is not None:
            raise self.open_error
        yield self.client


def make_principal(*, tenant_id: UUID | None = None) -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        username="admin",
        email="admin@example.test",
        roles=frozenset({"admin"}),
    )


def make_service(
    *,
    repository: FakeRepository | None = None,
    validator: FakeValidator | None = None,
    storage: FakeStorage | None = None,
    client: FakeDifyClient | None = None,
    stale_active_job_seconds: int = 300,
) -> tuple[
    KnowledgeDocumentsService,
    FakeRepository,
    FakeStorage,
    FakeDifyClient,
]:
    resolved_repository = repository or FakeRepository()
    resolved_storage = storage or FakeStorage()
    resolved_client = client or FakeDifyClient()
    service = KnowledgeDocumentsService(
        repository=resolved_repository,
        validator=validator or FakeValidator(),
        storage=resolved_storage,
        dify_factory=FakeFactory(resolved_client),
        stale_active_job_seconds=stale_active_job_seconds,
    )
    return service, resolved_repository, resolved_storage, resolved_client


def seed_document(
    repository: FakeRepository,
    storage: FakeStorage,
    principal: Principal,
    *,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.COMPLETED,
    dify_document_id: str | None = None,
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        uploaded_by_user_id=principal.user_id,
        original_filename="rules.txt",
        storage_key=f"{principal.tenant_id}/{uuid4()}.txt",
        media_type="text/plain",
        extension="txt",
        size_bytes=5,
        sha256="b" * 64,
        status=status,
        dify_document_id=dify_document_id or str(uuid4()),
        dify_indexing_status="completed",
    )
    repository._stamp_document(document)
    repository.documents[document.id] = document
    storage.files[document.storage_key] = b"rules"
    return document


def seed_job(
    repository: FakeRepository,
    principal: Principal,
    document: KnowledgeDocument,
    *,
    status: KnowledgeSyncJobStatus,
    operation: KnowledgeSyncOperation = KnowledgeSyncOperation.UPLOAD,
) -> KnowledgeSyncJob:
    job = KnowledgeSyncJob(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        document_id=document.id,
        created_by_user_id=principal.user_id,
        operation=operation,
        status=status,
        dify_batch_id="batch-status",
        dify_indexing_status="indexing",
    )
    repository._stamp_job(job)
    repository.jobs[job.id] = job
    return job


async def test_upload_persists_private_file_and_returns_safe_processing_contract() -> None:
    principal = make_principal()
    service, repository, storage, client = make_service()
    upload = UploadFile(file=BytesIO(b"ignored"), filename="rules.txt")

    response = await service.upload(principal, upload)

    assert response.document.status == KnowledgeDocumentStatus.PROCESSING
    assert response.job.status == KnowledgeSyncJobStatus.PROCESSING
    assert response.job.operation == KnowledgeSyncOperation.UPLOAD
    assert client.created_files == [
        ("rules.txt", "text/plain", "教学规则".encode())
    ]
    document = repository.documents[response.document.id]
    job = repository.jobs[response.job.id]
    assert storage.files[document.storage_key] == "教学规则".encode()
    assert document.dify_document_id == client.mutation_result.document_id
    assert job.dify_batch_id == client.mutation_result.batch
    public_json = response.model_dump_json()
    for protected in (
        "storage_key",
        "sha256",
        document.dify_document_id,
        job.dify_batch_id,
    ):
        assert protected not in public_json


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_status"),
    [
        (KnowledgeFileTooLargeError("large"), "knowledge_file_too_large", 413),
        (
            KnowledgeFileTypeNotSupportedError("type"),
            "knowledge_file_type_not_supported",
            415,
        ),
        (KnowledgeFileInvalidError("invalid"), "knowledge_file_invalid", 422),
    ],
)
async def test_upload_maps_file_validation_errors(
    error: Exception,
    expected_code: str,
    expected_status: int,
) -> None:
    service, repository, storage, _ = make_service(
        validator=FakeValidator(error=error),
    )

    with pytest.raises(AppError) as captured:
        await service.upload(
            make_principal(),
            UploadFile(file=BytesIO(b"ignored"), filename="rules.txt"),
        )

    assert captured.value.code == expected_code
    assert captured.value.status_code == expected_status
    assert repository.documents == {}
    assert storage.files == {}


async def test_upload_records_safe_failed_job_when_dify_authentication_fails() -> None:
    client = FakeDifyClient()
    client.create_error = DifyAuthenticationError("safe")
    service, repository, storage, _ = make_service(client=client)

    with pytest.raises(AppError) as captured:
        await service.upload(
            make_principal(),
            UploadFile(file=BytesIO(b"ignored"), filename="rules.txt"),
        )

    assert captured.value.code == "knowledge_document_upstream_authentication_failed"
    document = next(iter(repository.documents.values()))
    job = next(iter(repository.jobs.values()))
    assert document.status == KnowledgeDocumentStatus.FAILED
    assert job.status == KnowledgeSyncJobStatus.FAILED
    assert job.error_code == captured.value.code
    assert job.error_message == captured.value.message
    assert storage.files[document.storage_key]


async def test_upload_recovers_first_local_save_failure_after_dify_success() -> None:
    repository = FakeRepository()
    repository.save_failures_remaining = 1
    service, _, _, client = make_service(repository=repository)

    with pytest.raises(AppError) as captured:
        await service.upload(
            make_principal(),
            UploadFile(file=BytesIO(b"ignored"), filename="rules.txt"),
        )

    assert captured.value.code == "knowledge_document_state_persistence_failed"
    document = next(iter(repository.documents.values()))
    job = next(iter(repository.jobs.values()))
    assert document.status == KnowledgeDocumentStatus.FAILED
    assert document.dify_document_id == client.mutation_result.document_id
    assert job.status == KnowledgeSyncJobStatus.FAILED
    assert job.dify_batch_id == client.mutation_result.batch
    assert (
        await repository.get_active_job(
            tenant_id=document.tenant_id,
            document_id=document.id,
        )
        is None
    )


async def test_get_job_refreshes_processing_status_to_completed() -> None:
    principal = make_principal()
    service, repository, storage, client = make_service()
    document = seed_document(
        repository,
        storage,
        principal,
        status=KnowledgeDocumentStatus.PROCESSING,
    )
    job = seed_job(
        repository,
        principal,
        document,
        status=KnowledgeSyncJobStatus.PROCESSING,
    )
    client.indexing_statuses = (
        DifyDocumentIndexingStatus(
            document_id=document.dify_document_id or "",
            indexing_status="completed",
            error_present=False,
            completed_segments=4,
            total_segments=4,
        ),
    )

    response = await service.get_job(principal, job.id)

    assert response.status == KnowledgeSyncJobStatus.COMPLETED
    assert response.completed_segments == 4
    assert response.total_segments == 4
    assert document.status == KnowledgeDocumentStatus.COMPLETED
    assert document.completed_at is not None


async def test_get_job_maps_mismatched_dify_status_without_mutating_local_state() -> None:
    principal = make_principal()
    service, repository, storage, client = make_service()
    document = seed_document(
        repository,
        storage,
        principal,
        status=KnowledgeDocumentStatus.PROCESSING,
    )
    job = seed_job(
        repository,
        principal,
        document,
        status=KnowledgeSyncJobStatus.PROCESSING,
    )
    client.indexing_statuses = (
        DifyDocumentIndexingStatus(
            document_id=str(uuid4()),
            indexing_status="completed",
            error_present=False,
            completed_segments=1,
            total_segments=1,
        ),
    )

    with pytest.raises(AppError) as captured:
        await service.get_job(principal, job.id)

    assert captured.value.code == "knowledge_document_upstream_protocol_error"
    assert job.status == KnowledgeSyncJobStatus.PROCESSING
    assert document.status == KnowledgeDocumentStatus.PROCESSING


async def test_get_job_keeps_processing_state_on_transient_timeout() -> None:
    principal = make_principal()
    service, repository, storage, client = make_service()
    document = seed_document(
        repository,
        storage,
        principal,
        status=KnowledgeDocumentStatus.PROCESSING,
    )
    job = seed_job(
        repository,
        principal,
        document,
        status=KnowledgeSyncJobStatus.PROCESSING,
    )
    client.status_error = DifyTimeoutError("safe")

    with pytest.raises(AppError) as captured:
        await service.get_job(principal, job.id)

    assert captured.value.code == "knowledge_document_upstream_timeout"
    assert job.status == KnowledgeSyncJobStatus.PROCESSING
    assert document.status == KnowledgeDocumentStatus.PROCESSING


async def test_get_job_marks_stale_active_job_without_batch_as_failed() -> None:
    principal = make_principal()
    repository = FakeRepository()
    service, _, storage, _ = make_service(
        repository=repository,
        stale_active_job_seconds=1,
    )
    document = seed_document(
        repository,
        storage,
        principal,
        status=KnowledgeDocumentStatus.PENDING,
    )
    job = seed_job(
        repository,
        principal,
        document,
        status=KnowledgeSyncJobStatus.PENDING,
    )
    job.dify_batch_id = None
    job.started_at = datetime.now(UTC) - timedelta(seconds=2)

    response = await service.get_job(principal, job.id)

    assert response.status == KnowledgeSyncJobStatus.FAILED
    assert response.error_code == "knowledge_document_stale_active_job"
    assert document.status == KnowledgeDocumentStatus.FAILED


async def test_reindex_reads_private_original_and_creates_new_processing_job() -> None:
    principal = make_principal()
    service, repository, storage, client = make_service()
    document = seed_document(repository, storage, principal)
    original_dify_id = document.dify_document_id or ""
    client.mutation_result = DifyDocumentMutationResult(
        document_id=str(uuid4()),
        indexing_status="indexing",
        batch="batch-reindex",
    )

    response = await service.reindex(principal, document.id)

    assert response.document.status == KnowledgeDocumentStatus.PROCESSING
    assert response.job.operation == KnowledgeSyncOperation.REINDEX
    assert response.job.status == KnowledgeSyncJobStatus.PROCESSING
    assert client.updated_files == [
        (original_dify_id, "rules.txt", "text/plain", b"rules")
    ]
    assert document.dify_document_id == client.mutation_result.document_id


async def test_reindex_rejects_active_job_and_missing_original_file() -> None:
    principal = make_principal()
    service, repository, storage, _ = make_service()
    busy_document = seed_document(repository, storage, principal)
    seed_job(
        repository,
        principal,
        busy_document,
        status=KnowledgeSyncJobStatus.PROCESSING,
    )

    with pytest.raises(AppError) as busy:
        await service.reindex(principal, busy_document.id)
    assert busy.value.code == "knowledge_document_busy"

    missing_document = seed_document(repository, storage, principal)
    storage.files.pop(missing_document.storage_key)
    with pytest.raises(AppError) as missing:
        await service.reindex(principal, missing_document.id)
    assert missing.value.code == "knowledge_document_file_missing"


async def test_delete_treats_missing_upstream_document_as_idempotent_cleanup() -> None:
    principal = make_principal()
    service, repository, storage, client = make_service()
    document = seed_document(repository, storage, principal)
    client.delete_error = DifyNotFoundError("safe")

    response = await service.delete(principal, document.id)

    assert response.document.status == KnowledgeDocumentStatus.DELETED
    assert response.job.operation == KnowledgeSyncOperation.DELETE
    assert response.job.status == KnowledgeSyncJobStatus.COMPLETED
    assert document.deleted_at is not None
    assert document.storage_key not in storage.files
    listed = await service.list_documents(principal, limit=20, offset=0)
    assert listed.total == 0


async def test_delete_persists_upstream_phase_before_storage_failure_and_can_retry() -> None:
    principal = make_principal()
    storage = FakeStorage()
    storage.fail_delete = True
    service, repository, _, client = make_service(storage=storage)
    document = seed_document(repository, storage, principal)
    original_dify_id = document.dify_document_id

    with pytest.raises(AppError) as captured:
        await service.delete(principal, document.id)

    assert captured.value.code == "knowledge_storage_unavailable"
    failed_job = max(repository.jobs.values(), key=lambda item: item.created_at)
    assert original_dify_id in client.deleted_documents
    assert document.dify_document_id is None
    assert document.status == KnowledgeDocumentStatus.FAILED
    assert failed_job.status == KnowledgeSyncJobStatus.FAILED
    assert failed_job.dify_deleted_at is not None
    assert failed_job.file_deleted_at is None

    storage.fail_delete = False
    response = await service.delete(principal, document.id)

    assert response.document.status == KnowledgeDocumentStatus.DELETED
    assert response.job.status == KnowledgeSyncJobStatus.COMPLETED
    assert len(client.deleted_documents) == 1


async def test_cross_tenant_document_and_job_are_reported_as_not_found() -> None:
    owner = make_principal()
    outsider = make_principal()
    service, repository, storage, _ = make_service()
    document = seed_document(repository, storage, owner)
    job = seed_job(
        repository,
        owner,
        document,
        status=KnowledgeSyncJobStatus.COMPLETED,
    )

    with pytest.raises(AppError) as document_error:
        await service.get_document(outsider, document.id)
    with pytest.raises(AppError) as job_error:
        await service.get_job(outsider, job.id)

    assert document_error.value.code == "knowledge_document_not_found"
    assert job_error.value.code == "knowledge_job_not_found"
