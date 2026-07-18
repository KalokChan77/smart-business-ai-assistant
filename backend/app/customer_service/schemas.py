from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.customer_service.models import (
    CustomerServiceKnowledgeOutcome,
    CustomerTicket,
    CustomerTicketCategory,
    CustomerTicketPriority,
    CustomerTicketStatus,
    ReplyQualityStatus,
    ReplySuggestion,
    ReplySuggestionStatus,
)


class CustomerTicketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)

    @field_validator("subject", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CustomerTicketActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID


class ReplySuggestionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_reply: str | None = Field(default=None, min_length=1, max_length=5000)

    @field_validator("final_reply", mode="before")
    @classmethod
    def normalize_final_reply(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Final reply must not be empty.")
        return normalized


class CustomerServiceCitationResponse(BaseModel):
    rank: int = Field(ge=1)
    document_name: str
    excerpt: str
    score: float | None = None


class ReplySuggestionResponse(BaseModel):
    id: UUID
    ticket_id: UUID
    status: ReplySuggestionStatus
    category: CustomerTicketCategory
    suggested_reply: str
    final_reply: str | None
    knowledge_outcome: CustomerServiceKnowledgeOutcome
    citations: list[CustomerServiceCitationResponse]
    quality_status: ReplyQualityStatus
    quality_notes: list[str]
    workflow_version: str
    generated_by_user_id: UUID | None
    confirmed_by_user_id: UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, suggestion: ReplySuggestion) -> "ReplySuggestionResponse":
        return cls(
            id=suggestion.id,
            ticket_id=suggestion.ticket_id,
            status=suggestion.status,
            category=suggestion.category,
            suggested_reply=suggestion.suggested_reply,
            final_reply=suggestion.final_reply,
            knowledge_outcome=suggestion.knowledge_outcome,
            citations=[
                CustomerServiceCitationResponse.model_validate(item)
                for item in suggestion.citations
            ],
            quality_status=suggestion.quality_status,
            quality_notes=[str(item) for item in suggestion.quality_notes],
            workflow_version=suggestion.workflow_version,
            generated_by_user_id=suggestion.generated_by_user_id,
            confirmed_by_user_id=suggestion.confirmed_by_user_id,
            confirmed_at=suggestion.confirmed_at,
            created_at=suggestion.created_at,
            updated_at=suggestion.updated_at,
        )


class ConfirmedReplyPublicResponse(BaseModel):
    final_reply: str
    confirmed_at: datetime

    @classmethod
    def from_entity(
        cls,
        suggestion: ReplySuggestion,
    ) -> "ConfirmedReplyPublicResponse":
        if (
            suggestion.status != ReplySuggestionStatus.CONFIRMED
            or suggestion.final_reply is None
            or suggestion.confirmed_at is None
        ):
            raise ValueError("Only confirmed replies can be exposed publicly.")
        return cls(
            final_reply=suggestion.final_reply,
            confirmed_at=suggestion.confirmed_at,
        )


class CustomerTicketPublicResponse(BaseModel):
    id: UUID
    subject: str
    description: str
    status: CustomerTicketStatus
    category: CustomerTicketCategory | None
    priority: CustomerTicketPriority
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, ticket: CustomerTicket) -> "CustomerTicketPublicResponse":
        return cls(
            id=ticket.id,
            subject=ticket.subject,
            description=ticket.description,
            status=ticket.status,
            category=ticket.category,
            priority=ticket.priority,
            resolved_at=ticket.resolved_at,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )


class CustomerTicketInternalResponse(CustomerTicketPublicResponse):
    requester_user_id: UUID
    assigned_user_id: UUID | None
    classification_confidence: int | None = Field(default=None, ge=0, le=100)
    classification_reason: str | None

    @classmethod
    def from_entity(
        cls,
        ticket: CustomerTicket,
    ) -> "CustomerTicketInternalResponse":
        return cls(
            id=ticket.id,
            subject=ticket.subject,
            description=ticket.description,
            status=ticket.status,
            category=ticket.category,
            priority=ticket.priority,
            resolved_at=ticket.resolved_at,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            requester_user_id=ticket.requester_user_id,
            assigned_user_id=ticket.assigned_user_id,
            classification_confidence=ticket.classification_confidence,
            classification_reason=ticket.classification_reason,
        )


class CustomerTicketListResponse(BaseModel):
    items: list[CustomerTicketPublicResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class CustomerTicketPublicDetailResponse(BaseModel):
    view: Literal["public"] = "public"
    ticket: CustomerTicketPublicResponse
    confirmed_reply: ConfirmedReplyPublicResponse | None


class CustomerTicketInternalDetailResponse(BaseModel):
    view: Literal["internal"] = "internal"
    ticket: CustomerTicketInternalResponse
    reply_suggestion: ReplySuggestionResponse | None


CustomerTicketDetailResponse = Annotated[
    CustomerTicketPublicDetailResponse | CustomerTicketInternalDetailResponse,
    Field(discriminator="view"),
]


class CustomerTicketClassificationResponse(BaseModel):
    ticket_id: UUID
    category: CustomerTicketCategory
    priority: CustomerTicketPriority
    confidence: int = Field(ge=0, le=100)
    reason: str
    status: CustomerTicketStatus
    assigned_user_id: UUID | None

    @classmethod
    def from_entity(
        cls,
        ticket: CustomerTicket,
    ) -> "CustomerTicketClassificationResponse":
        if ticket.category is None or ticket.classification_confidence is None:
            raise ValueError("Ticket classification is incomplete.")
        return cls(
            ticket_id=ticket.id,
            category=ticket.category,
            priority=ticket.priority,
            confidence=ticket.classification_confidence,
            reason=ticket.classification_reason or "",
            status=ticket.status,
            assigned_user_id=ticket.assigned_user_id,
        )
