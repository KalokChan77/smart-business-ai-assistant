from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class CustomerTicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class CustomerTicketCategory(StrEnum):
    REFUND_AFTER_SALES = "refund_after_sales"
    ACCOUNT_SECURITY = "account_security"
    PRODUCT_SERVICE = "product_service"
    KNOWLEDGE_DOCUMENT = "knowledge_document"
    TECHNICAL_SUPPORT = "technical_support"
    OTHER = "other"


class CustomerTicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReplySuggestionStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class ReplyQualityStatus(StrEnum):
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"


class CustomerServiceKnowledgeOutcome(StrEnum):
    ANSWERED = "answered"
    NO_MATCH = "no_match"
    REFUSED = "refused"


class CustomerTicket(TimestampMixin, Base):
    __tablename__ = "customer_tickets"
    __table_args__ = (
        CheckConstraint(
            "char_length(subject) BETWEEN 1 AND 200",
            name="customer_ticket_subject_length",
        ),
        CheckConstraint(
            "char_length(description) BETWEEN 1 AND 10000",
            name="customer_ticket_description_length",
        ),
        CheckConstraint(
            "classification_confidence IS NULL OR "
            "classification_confidence BETWEEN 0 AND 100",
            name="customer_ticket_classification_confidence_range",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_customer_tickets_id_tenant_id",
        ),
        ForeignKeyConstraint(
            ["requester_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_customer_tickets_requester_tenant_users",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assigned_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_customer_tickets_assigned_tenant_users",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_customer_tickets_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_customer_tickets_tenant_category_created",
            "tenant_id",
            "category",
            "created_at",
        ),
        Index(
            "ix_customer_tickets_requester_created",
            "requester_user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    requester_user_id: Mapped[UUID] = mapped_column(index=True)
    assigned_user_id: Mapped[UUID | None] = mapped_column(index=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CustomerTicketStatus] = mapped_column(
        Enum(
            CustomerTicketStatus,
            name="customer_ticket_status",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=CustomerTicketStatus.OPEN,
        server_default=CustomerTicketStatus.OPEN.value,
    )
    category: Mapped[CustomerTicketCategory | None] = mapped_column(
        Enum(
            CustomerTicketCategory,
            name="customer_ticket_category",
            native_enum=False,
            length=40,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
    )
    priority: Mapped[CustomerTicketPriority] = mapped_column(
        Enum(
            CustomerTicketPriority,
            name="customer_ticket_priority",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=CustomerTicketPriority.NORMAL,
        server_default=CustomerTicketPriority.NORMAL.value,
    )
    classification_confidence: Mapped[int | None] = mapped_column(Integer)
    classification_reason: Mapped[str | None] = mapped_column(String(500))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReplySuggestion(TimestampMixin, Base):
    __tablename__ = "reply_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id",
            name="uq_reply_suggestions_ticket_id",
        ),
        CheckConstraint(
            "char_length(suggested_reply) BETWEEN 1 AND 5000",
            name="reply_suggestion_suggested_reply_length",
        ),
        CheckConstraint(
            "final_reply IS NULL OR char_length(final_reply) BETWEEN 1 AND 5000",
            name="reply_suggestion_final_reply_length",
        ),
        CheckConstraint(
            "(status = 'draft' AND final_reply IS NULL "
            "AND confirmed_by_user_id IS NULL AND confirmed_at IS NULL) "
            "OR (status = 'confirmed' AND final_reply IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="reply_suggestion_confirmation_consistency",
        ),
        ForeignKeyConstraint(
            ["ticket_id", "tenant_id"],
            ["customer_tickets.id", "customer_tickets.tenant_id"],
            name="fk_reply_suggestions_ticket_tenant_customer_tickets",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["generated_by_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_reply_suggestions_generated_tenant_users",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_reply_suggestions_confirmed_tenant_users",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_reply_suggestions_tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    category: Mapped[CustomerTicketCategory] = mapped_column(
        Enum(
            CustomerTicketCategory,
            name="reply_suggestion_category",
            native_enum=False,
            length=40,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    status: Mapped[ReplySuggestionStatus] = mapped_column(
        Enum(
            ReplySuggestionStatus,
            name="reply_suggestion_status",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=ReplySuggestionStatus.DRAFT,
        server_default=ReplySuggestionStatus.DRAFT.value,
    )
    suggested_reply: Mapped[str] = mapped_column(Text, nullable=False)
    final_reply: Mapped[str | None] = mapped_column(Text)
    knowledge_outcome: Mapped[CustomerServiceKnowledgeOutcome] = mapped_column(
        Enum(
            CustomerServiceKnowledgeOutcome,
            name="customer_service_knowledge_outcome",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    citations: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    quality_status: Mapped[ReplyQualityStatus] = mapped_column(
        Enum(
            ReplyQualityStatus,
            name="reply_quality_status",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    quality_notes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    workflow_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="customer-service-v1",
        server_default="customer-service-v1",
    )
    generated_by_user_id: Mapped[UUID | None] = mapped_column(index=True)
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
