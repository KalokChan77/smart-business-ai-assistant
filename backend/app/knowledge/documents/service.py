from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import UploadFile, status

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyClientError,
    DifyConfigurationError,
    DifyNotFoundError,
    DifyProtocolError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.ai.dify.factory import DifyDatasetClientFactory
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
    KnowledgeDocumentsRepository,
    KnowledgeRepositoryError,
)
from app.knowledge.documents.schemas import (
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOperationResponse,
    KnowledgeDocumentResponse,
    KnowledgeSyncJobResponse,
)
from app.knowledge.documents.storage import (
    KnowledgeFileStorage,
    KnowledgeStorageError,
    KnowledgeStoredFileMissingError,
)
from app.knowledge.documents.validation import (
    KnowledgeFileInvalidError,
    KnowledgeFileTooLargeError,
    KnowledgeFileTypeNotSupportedError,
    KnowledgeFileValidator,
    KnowledgeFileValidationError,
)

_PROCESSING_INDEXING_STATUSES = {
    "waiting",
    "parsing",
    "cleaning",
    "splitting",
    "indexing",
    "paused",
}
_FAILED_INDEXING_STATUSES = {"error", "stopped"}


class KnowledgeDocumentsService:
    def __init__(
        self,
        *,
        repository: KnowledgeDocumentsRepository,
        validator: KnowledgeFileValidator,
        storage: KnowledgeFileStorage,
        dify_factory: DifyDatasetClientFactory,
        stale_active_job_seconds: int = 300,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._storage = storage
        self._dify_factory = dify_factory
        self._stale_active_job_after = timedelta(
            seconds=max(stale_active_job_seconds, 1)
        )

    async def upload(
        self,
        principal: Principal,
        upload: UploadFile,
    ) -> KnowledgeDocumentOperationResponse:
        validated = await self._validate_upload(upload)
        document_id = uuid4()
        try:
            storage_key = await self._storage.save(
                tenant_id=principal.tenant_id,
                document_id=document_id,
                extension=validated.extension,
                content=validated.content,
            )
        except KnowledgeStorageError as exc:
            raise self._storage_unavailable() from exc

        document = KnowledgeDocument(
            id=document_id,
            tenant_id=principal.tenant_id,
            uploaded_by_user_id=principal.user_id,
            original_filename=validated.filename,
            storage_key=storage_key,
            media_type=validated.media_type,
            extension=validated.extension,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
            status=KnowledgeDocumentStatus.PENDING,
        )
        job = self._new_job(
            principal=principal,
            document=document,
            operation=KnowledgeSyncOperation.UPLOAD,
        )
        try:
            await self._repository.create_upload(document, job)
        except KnowledgeRepositoryError as exc:
            try:
                await self._storage.delete(storage_key)
            except KnowledgeStorageError:
                pass
            raise self._persistence_unavailable() from exc

        try:
            async with self._dify_factory.open() as client:
                result = await client.create_document_by_file(
                    filename=validated.filename,
                    media_type=validated.media_type,
                    content=validated.content,
                )
        except DifyClientError as exc:
            await self._record_operation_failure(
                document=document,
                job=job,
                exc=exc,
                mark_document_failed=True,
            )

        await self._persist_mutation_result(
            document=document,
            job=job,
            result=result,
            previous_dify_document_id=None,
        )
        return KnowledgeDocumentOperationResponse.from_entities(document, job)

    async def list_documents(
        self,
        principal: Principal,
        *,
        limit: int,
        offset: int,
    ) -> KnowledgeDocumentListResponse:
        documents, total = await self._repository.list_documents(
            tenant_id=principal.tenant_id,
            limit=limit,
            offset=offset,
        )
        return KnowledgeDocumentListResponse(
            items=[KnowledgeDocumentResponse.from_entity(item) for item in documents],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_document(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocumentResponse:
        document = await self._require_document(principal, document_id)
        return KnowledgeDocumentResponse.from_entity(document)

    async def get_job(
        self,
        principal: Principal,
        job_id: UUID,
    ) -> KnowledgeSyncJobResponse:
        job = await self._repository.get_job(
            tenant_id=principal.tenant_id,
            job_id=job_id,
        )
        if job is None:
            raise self._job_not_found()
        if job.status not in {
            KnowledgeSyncJobStatus.PENDING,
            KnowledgeSyncJobStatus.PROCESSING,
        }:
            return KnowledgeSyncJobResponse.from_entity(job)
        if not job.dify_batch_id:
            return await self._recover_stale_active_job(principal, job)

        document = await self._repository.get_document(
            tenant_id=principal.tenant_id,
            document_id=job.document_id,
            include_deleted=True,
        )
        if document is None or not document.dify_document_id:
            raise AppError(
                code="knowledge_document_state_invalid",
                message="知识文档任务状态不完整。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            async with self._dify_factory.open() as client:
                statuses = await client.get_document_indexing_status(
                    batch=job.dify_batch_id,
                )
            indexing_status = self._select_document_status(document, statuses)
        except DifyClientError as exc:
            raise self._map_dify_error(exc) from exc

        self._apply_indexing_status(document, job, indexing_status)
        await self._save_or_raise_persistence_error(document, job)
        return KnowledgeSyncJobResponse.from_entity(job)

    async def reindex(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocumentOperationResponse:
        document = await self._require_document(principal, document_id)
        await self._ensure_not_busy(principal, document.id)
        if not document.dify_document_id:
            raise AppError(
                code="knowledge_document_not_indexed",
                message="知识文档尚未建立可更新的索引。",
                status_code=status.HTTP_409_CONFLICT,
            )
        try:
            content = await self._storage.read(document.storage_key)
        except KnowledgeStoredFileMissingError as exc:
            raise AppError(
                code="knowledge_document_file_missing",
                message="知识文档原文件缺失，无法重新索引。",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        except KnowledgeStorageError as exc:
            raise self._storage_unavailable() from exc

        job = self._new_job(
            principal=principal,
            document=document,
            operation=KnowledgeSyncOperation.REINDEX,
        )
        await self._create_job(job)
        previous_dify_document_id = document.dify_document_id
        try:
            async with self._dify_factory.open() as client:
                result = await client.update_document_by_file(
                    document_id=document.dify_document_id,
                    filename=document.original_filename,
                    media_type=document.media_type,
                    content=content,
                )
        except DifyClientError as exc:
            await self._record_operation_failure(
                document=document,
                job=job,
                exc=exc,
                mark_document_failed=True,
            )

        await self._persist_mutation_result(
            document=document,
            job=job,
            result=result,
            previous_dify_document_id=previous_dify_document_id,
        )
        return KnowledgeDocumentOperationResponse.from_entities(document, job)

    async def delete(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocumentOperationResponse:
        document = await self._require_document(principal, document_id)
        await self._ensure_not_busy(principal, document.id)
        job = self._new_job(
            principal=principal,
            document=document,
            operation=KnowledgeSyncOperation.DELETE,
        )
        job.status = KnowledgeSyncJobStatus.PROCESSING
        await self._create_job(job)

        if document.dify_document_id:
            try:
                async with self._dify_factory.open() as client:
                    await client.delete_document(
                        document_id=document.dify_document_id,
                    )
            except DifyNotFoundError:
                pass
            except DifyClientError as exc:
                await self._record_operation_failure(
                    document=document,
                    job=job,
                    exc=exc,
                    mark_document_failed=False,
                )

        document.dify_document_id = None
        job.dify_deleted_at = datetime.now(UTC)
        await self._persist_delete_phase(document, job)

        try:
            await self._storage.delete(document.storage_key)
        except KnowledgeStorageError as exc:
            await self._record_app_failure(
                document=document,
                job=job,
                app_error=self._storage_unavailable(),
                cause=exc,
                mark_document_failed=True,
            )

        job.file_deleted_at = datetime.now(UTC)
        await self._persist_delete_phase(document, job)

        now = datetime.now(UTC)
        document.status = KnowledgeDocumentStatus.DELETED
        document.dify_indexing_status = None
        document.latest_error_code = None
        document.deleted_at = now
        document.deleted_by_user_id = principal.user_id
        job.status = KnowledgeSyncJobStatus.COMPLETED
        job.dify_indexing_status = None
        job.error_code = None
        job.error_message = None
        job.completed_at = now
        try:
            await self._repository.save(document, job)
        except KnowledgeRepositoryError as exc:
            document.status = KnowledgeDocumentStatus.FAILED
            document.deleted_at = None
            document.deleted_by_user_id = None
            job.status = KnowledgeSyncJobStatus.FAILED
            job.completed_at = None
            await self._record_app_failure(
                document=document,
                job=job,
                app_error=self._persistence_unavailable(),
                cause=exc,
                mark_document_failed=True,
            )
        return KnowledgeDocumentOperationResponse.from_entities(document, job)

    async def _validate_upload(self, upload: UploadFile):
        try:
            return await self._validator.read_and_validate(upload)
        except KnowledgeFileTooLargeError as exc:
            raise AppError(
                code="knowledge_file_too_large",
                message="知识文档超过允许的大小限制。",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            ) from exc
        except KnowledgeFileTypeNotSupportedError as exc:
            raise AppError(
                code="knowledge_file_type_not_supported",
                message="知识文档类型不受支持。",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            ) from exc
        except KnowledgeFileInvalidError as exc:
            raise AppError(
                code="knowledge_file_invalid",
                message="知识文档内容或文件结构无效。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc
        except KnowledgeFileValidationError as exc:
            raise AppError(
                code="knowledge_file_invalid",
                message="知识文档校验失败。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc

    async def _require_document(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocument:
        document = await self._repository.get_document(
            tenant_id=principal.tenant_id,
            document_id=document_id,
        )
        if document is None:
            raise AppError(
                code="knowledge_document_not_found",
                message="知识文档不存在。",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return document

    async def _ensure_not_busy(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> None:
        active_job = await self._repository.get_active_job(
            tenant_id=principal.tenant_id,
            document_id=document_id,
        )
        if active_job is not None:
            raise self._document_busy()

    async def _create_job(self, job: KnowledgeSyncJob) -> None:
        try:
            await self._repository.create_job(job)
        except KnowledgeDocumentBusyRepositoryError as exc:
            raise self._document_busy() from exc
        except KnowledgeRepositoryError as exc:
            raise self._persistence_unavailable() from exc

    async def _persist_mutation_result(
        self,
        *,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
        result: DifyDocumentMutationResult,
        previous_dify_document_id: str | None,
    ) -> None:
        self._apply_mutation_result(document, job, result)
        try:
            await self._repository.save(document, job)
        except KnowledgeRepositoryError as exc:
            await self._recover_mutation_persistence_failure(
                document=document,
                job=job,
                result=result,
                previous_dify_document_id=previous_dify_document_id,
                cause=exc,
            )

    async def _recover_mutation_persistence_failure(
        self,
        *,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
        result: DifyDocumentMutationResult,
        previous_dify_document_id: str | None,
        cause: Exception,
    ) -> NoReturn:
        app_error = self._persistence_unavailable()
        now = datetime.now(UTC)
        document.dify_document_id = result.document_id
        document.dify_indexing_status = result.indexing_status
        document.status = KnowledgeDocumentStatus.FAILED
        document.latest_error_code = app_error.code
        document.completed_at = None
        job.dify_batch_id = result.batch
        job.dify_indexing_status = result.indexing_status
        job.status = KnowledgeSyncJobStatus.FAILED
        job.error_code = app_error.code
        job.error_message = app_error.message
        job.completed_at = now
        try:
            await self._repository.save(document, job)
        except KnowledgeRepositoryError as retry_exc:
            if (
                job.operation == KnowledgeSyncOperation.UPLOAD
                or (
                    job.operation == KnowledgeSyncOperation.REINDEX
                    and previous_dify_document_id is None
                )
            ):
                await self._best_effort_delete_dify_document(result.document_id)
            raise app_error from retry_exc
        raise app_error from cause

    async def _persist_delete_phase(
        self,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> None:
        try:
            await self._repository.save(document, job)
        except KnowledgeRepositoryError as exc:
            await self._record_app_failure(
                document=document,
                job=job,
                app_error=self._persistence_unavailable(),
                cause=exc,
                mark_document_failed=True,
            )

    async def _best_effort_delete_dify_document(self, document_id: str) -> None:
        try:
            async with self._dify_factory.open() as client:
                await client.delete_document(document_id=document_id)
        except DifyClientError:
            pass

    async def _recover_stale_active_job(
        self,
        principal: Principal,
        job: KnowledgeSyncJob,
    ) -> KnowledgeSyncJobResponse:
        now = datetime.now(UTC)
        if now - job.started_at < self._stale_active_job_after:
            return KnowledgeSyncJobResponse.from_entity(job)
        document = await self._repository.get_document(
            tenant_id=principal.tenant_id,
            document_id=job.document_id,
            include_deleted=True,
        )
        if document is None:
            raise self._job_not_found()
        document.status = KnowledgeDocumentStatus.FAILED
        document.latest_error_code = "knowledge_document_stale_active_job"
        document.completed_at = None
        job.status = KnowledgeSyncJobStatus.FAILED
        job.error_code = "knowledge_document_stale_active_job"
        job.error_message = "知识文档同步任务未能完成状态持久化。"
        job.completed_at = now
        await self._save_or_raise_persistence_error(document, job)
        return KnowledgeSyncJobResponse.from_entity(job)

    async def _save_or_raise_persistence_error(
        self,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> None:
        try:
            await self._repository.save(document, job)
        except KnowledgeRepositoryError as exc:
            raise self._persistence_unavailable() from exc

    @staticmethod
    def _new_job(
        *,
        principal: Principal,
        document: KnowledgeDocument,
        operation: KnowledgeSyncOperation,
    ) -> KnowledgeSyncJob:
        return KnowledgeSyncJob(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            document_id=document.id,
            created_by_user_id=principal.user_id,
            operation=operation,
            status=KnowledgeSyncJobStatus.PENDING,
        )

    @staticmethod
    def _apply_mutation_result(
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
        result: DifyDocumentMutationResult,
    ) -> None:
        document.dify_document_id = result.document_id
        document.dify_indexing_status = result.indexing_status
        document.latest_error_code = None
        document.completed_at = None
        job.dify_batch_id = result.batch
        job.dify_indexing_status = result.indexing_status
        job.completed_segments = 0
        job.total_segments = 0
        job.error_code = None
        job.error_message = None
        job.completed_at = None

        if result.indexing_status in _PROCESSING_INDEXING_STATUSES:
            document.status = KnowledgeDocumentStatus.PROCESSING
            job.status = KnowledgeSyncJobStatus.PROCESSING
            return
        now = datetime.now(UTC)
        if result.indexing_status == "completed":
            document.status = KnowledgeDocumentStatus.COMPLETED
            document.completed_at = now
            job.status = KnowledgeSyncJobStatus.COMPLETED
            job.completed_at = now
            return
        document.status = KnowledgeDocumentStatus.FAILED
        document.latest_error_code = "knowledge_document_indexing_failed"
        job.status = KnowledgeSyncJobStatus.FAILED
        job.error_code = "knowledge_document_indexing_failed"
        job.error_message = "Dify 文档索引失败。"
        job.completed_at = now

    @staticmethod
    def _apply_indexing_status(
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
        indexing_status: DifyDocumentIndexingStatus,
    ) -> None:
        document.dify_indexing_status = indexing_status.indexing_status
        job.dify_indexing_status = indexing_status.indexing_status
        job.completed_segments = indexing_status.completed_segments
        job.total_segments = indexing_status.total_segments

        if indexing_status.indexing_status in _PROCESSING_INDEXING_STATUSES:
            document.status = KnowledgeDocumentStatus.PROCESSING
            document.latest_error_code = None
            document.completed_at = None
            job.status = KnowledgeSyncJobStatus.PROCESSING
            job.error_code = None
            job.error_message = None
            job.completed_at = None
            return

        now = datetime.now(UTC)
        if indexing_status.indexing_status == "completed":
            document.status = KnowledgeDocumentStatus.COMPLETED
            document.latest_error_code = None
            document.completed_at = now
            job.status = KnowledgeSyncJobStatus.COMPLETED
            job.error_code = None
            job.error_message = None
            job.completed_at = now
            return

        document.status = KnowledgeDocumentStatus.FAILED
        document.latest_error_code = "knowledge_document_indexing_failed"
        document.completed_at = None
        job.status = KnowledgeSyncJobStatus.FAILED
        job.error_code = "knowledge_document_indexing_failed"
        job.error_message = "Dify 文档索引失败。"
        job.completed_at = now

    @staticmethod
    def _select_document_status(
        document: KnowledgeDocument,
        statuses: tuple[DifyDocumentIndexingStatus, ...],
    ) -> DifyDocumentIndexingStatus:
        matching = [
            item for item in statuses if item.document_id == document.dify_document_id
        ]
        if len(matching) != 1:
            raise DifyProtocolError("Dify indexing status did not match the document.")
        return matching[0]

    async def _record_operation_failure(
        self,
        *,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
        exc: DifyClientError,
        mark_document_failed: bool,
    ) -> NoReturn:
        await self._record_app_failure(
            document=document,
            job=job,
            app_error=self._map_dify_error(exc),
            cause=exc,
            mark_document_failed=mark_document_failed,
        )

    async def _record_app_failure(
        self,
        *,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
        app_error: AppError,
        cause: Exception,
        mark_document_failed: bool,
    ) -> NoReturn:
        now = datetime.now(UTC)
        if mark_document_failed:
            document.status = KnowledgeDocumentStatus.FAILED
            document.completed_at = None
        document.latest_error_code = app_error.code
        job.status = KnowledgeSyncJobStatus.FAILED
        job.error_code = app_error.code
        job.error_message = app_error.message
        job.completed_at = now
        try:
            await self._repository.save(document, job)
        except KnowledgeRepositoryError as persistence_exc:
            raise self._persistence_unavailable() from persistence_exc
        raise app_error from cause

    @staticmethod
    def _map_dify_error(exc: DifyClientError) -> AppError:
        if isinstance(exc, DifyConfigurationError):
            return AppError(
                code="knowledge_service_not_configured",
                message="知识库文档服务尚未完成配置。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if isinstance(exc, DifyAuthenticationError):
            return AppError(
                code="knowledge_document_upstream_authentication_failed",
                message="知识库文档服务认证失败，请检查服务端配置。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        if isinstance(exc, DifyNotFoundError):
            return AppError(
                code="knowledge_document_upstream_not_found",
                message="知识库中的目标文档或任务不存在。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        if isinstance(exc, DifyRateLimitError):
            return AppError(
                code="knowledge_document_upstream_rate_limited",
                message="知识库文档服务当前请求较多，请稍后重试。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if isinstance(exc, DifyTimeoutError):
            return AppError(
                code="knowledge_document_upstream_timeout",
                message="知识库文档服务响应超时，请稍后重试。",
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        if isinstance(exc, DifyUnavailableError):
            return AppError(
                code="knowledge_document_upstream_unavailable",
                message="知识库文档服务暂时不可用，请稍后重试。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        if isinstance(exc, DifyRejectedError):
            return AppError(
                code="knowledge_document_upstream_rejected",
                message="知识库文档服务拒绝了本次操作。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        if isinstance(exc, DifyProtocolError):
            return AppError(
                code="knowledge_document_upstream_protocol_error",
                message="知识库文档服务返回了无法识别的结果。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return AppError(
            code="knowledge_document_upstream_unavailable",
            message="知识库文档服务暂时不可用，请稍后重试。",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    @staticmethod
    def _storage_unavailable() -> AppError:
        return AppError(
            code="knowledge_storage_unavailable",
            message="知识文档私有存储暂时不可用。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _persistence_unavailable() -> AppError:
        return AppError(
            code="knowledge_document_state_persistence_failed",
            message="知识文档状态暂时无法持久化，请稍后重试。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _document_busy() -> AppError:
        return AppError(
            code="knowledge_document_busy",
            message="知识文档当前已有同步任务正在执行。",
            status_code=status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _job_not_found() -> AppError:
        return AppError(
            code="knowledge_job_not_found",
            message="知识文档同步任务不存在。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
