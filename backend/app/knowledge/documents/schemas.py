from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.knowledge.documents.models import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSyncJob,
    KnowledgeSyncJobStatus,
    KnowledgeSyncOperation,
)


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    filename: str
    media_type: str
    extension: str
    size_bytes: int = Field(gt=0)
    status: KnowledgeDocumentStatus
    indexing_status: str | None
    latest_error_code: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, document: KnowledgeDocument) -> "KnowledgeDocumentResponse":
        return cls(
            id=document.id,
            filename=document.original_filename,
            media_type=document.media_type,
            extension=document.extension,
            size_bytes=document.size_bytes,
            status=document.status,
            indexing_status=document.dify_indexing_status,
            latest_error_code=document.latest_error_code,
            completed_at=document.completed_at,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class KnowledgeSyncJobResponse(BaseModel):
    id: UUID
    document_id: UUID
    operation: KnowledgeSyncOperation
    status: KnowledgeSyncJobStatus
    indexing_status: str | None
    completed_segments: int | None = Field(default=None, ge=0)
    total_segments: int | None = Field(default=None, ge=0)
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, job: KnowledgeSyncJob) -> "KnowledgeSyncJobResponse":
        return cls(
            id=job.id,
            document_id=job.document_id,
            operation=job.operation,
            status=job.status,
            indexing_status=job.dify_indexing_status,
            completed_segments=job.completed_segments,
            total_segments=job.total_segments,
            error_code=job.error_code,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class KnowledgeDocumentOperationResponse(BaseModel):
    document: KnowledgeDocumentResponse
    job: KnowledgeSyncJobResponse

    @classmethod
    def from_entities(
        cls,
        document: KnowledgeDocument,
        job: KnowledgeSyncJob,
    ) -> "KnowledgeDocumentOperationResponse":
        return cls(
            document=KnowledgeDocumentResponse.from_entity(document),
            job=KnowledgeSyncJobResponse.from_entity(job),
        )


class KnowledgeDocumentListResponse(BaseModel):
    items: list[KnowledgeDocumentResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
