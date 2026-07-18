from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class KnowledgeDocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class KnowledgeSyncOperation(StrEnum):
    UPLOAD = "upload"
    REINDEX = "reindex"
    DELETE = "delete"


class KnowledgeSyncJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "dify_document_id",
            name="uq_knowledge_documents_dify_document_id",
        ),
        UniqueConstraint(
            "storage_key",
            name="uq_knowledge_documents_storage_key",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="knowledge_document_size_positive",
        ),
        Index(
            "ix_knowledge_documents_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_knowledge_documents_tenant_deleted_created",
            "tenant_id",
            "deleted_at",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column()
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        Enum(
            KnowledgeDocumentStatus,
            name="knowledge_document_status",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=KnowledgeDocumentStatus.PENDING,
        server_default=KnowledgeDocumentStatus.PENDING.value,
    )
    dify_document_id: Mapped[str | None] = mapped_column(String(36))
    dify_indexing_status: Mapped[str | None] = mapped_column(String(32))
    latest_error_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )


class KnowledgeSyncJob(TimestampMixin, Base):
    __tablename__ = "knowledge_sync_jobs"
    __table_args__ = (
        CheckConstraint(
            "completed_segments IS NULL OR completed_segments >= 0",
            name="knowledge_sync_completed_segments_non_negative",
        ),
        CheckConstraint(
            "total_segments IS NULL OR total_segments >= 0",
            name="knowledge_sync_total_segments_non_negative",
        ),
        CheckConstraint(
            "completed_segments IS NULL OR total_segments IS NULL "
            "OR completed_segments <= total_segments",
            name="knowledge_sync_completed_not_above_total",
        ),
        Index(
            "ix_knowledge_sync_jobs_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_knowledge_sync_jobs_document_created",
            "document_id",
            "created_at",
        ),
        Index(
            "uq_knowledge_sync_jobs_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
            sqlite_where=text("status IN ('pending', 'processing')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column()
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    operation: Mapped[KnowledgeSyncOperation] = mapped_column(
        Enum(
            KnowledgeSyncOperation,
            name="knowledge_sync_operation",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    status: Mapped[KnowledgeSyncJobStatus] = mapped_column(
        Enum(
            KnowledgeSyncJobStatus,
            name="knowledge_sync_job_status",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=KnowledgeSyncJobStatus.PENDING,
        server_default=KnowledgeSyncJobStatus.PENDING.value,
    )
    dify_batch_id: Mapped[str | None] = mapped_column(String(64))
    dify_indexing_status: Mapped[str | None] = mapped_column(String(32))
    dify_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_segments: Mapped[int | None] = mapped_column(Integer)
    total_segments: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
