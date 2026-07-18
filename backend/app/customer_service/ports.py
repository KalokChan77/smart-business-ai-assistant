from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.auth.principal import Principal
from app.customer_service.models import (
    CustomerServiceKnowledgeOutcome,
    CustomerTicket,
    CustomerTicketCategory,
    CustomerTicketPriority,
    CustomerTicketStatus,
    ReplyQualityStatus,
    ReplySuggestion,
)


class CustomerTicketNotFoundError(Exception):
    """Raised when the current principal cannot see the requested ticket."""


class CustomerTicketNotActionableError(Exception):
    """Raised when an already completed ticket cannot be processed again."""


class ReplySuggestionNotFoundError(Exception):
    """Raised when a suggestion is absent or belongs to another tenant."""


class ReplySuggestionAlreadyConfirmedError(Exception):
    """Raised when confirmed content would be changed or regenerated."""


class CustomerServiceRepositoryError(Exception):
    """Raised when customer-service state cannot be persisted or read."""


@dataclass(frozen=True, slots=True)
class TicketClassification:
    category: CustomerTicketCategory
    priority: CustomerTicketPriority
    confidence: int
    reason: str


@dataclass(frozen=True, slots=True)
class CustomerServiceCitation:
    rank: int
    document_name: str
    excerpt: str
    score: float | None


@dataclass(frozen=True, slots=True)
class CustomerServiceKnowledgeResult:
    outcome: CustomerServiceKnowledgeOutcome
    answer: str
    citations: tuple[CustomerServiceCitation, ...]


@dataclass(frozen=True, slots=True)
class CustomerServiceWorkflowResult:
    classification: TicketClassification
    suggested_reply: str
    knowledge: CustomerServiceKnowledgeResult
    quality_status: ReplyQualityStatus
    quality_notes: tuple[str, ...]
    workflow_version: str


class TicketClassifier(Protocol):
    def classify(self, subject: str, description: str) -> TicketClassification: ...


class CustomerServiceKnowledgePort(Protocol):
    async def answer(
        self,
        principal: Principal,
        query: str,
    ) -> CustomerServiceKnowledgeResult: ...


class CustomerServiceWorkflowPort(Protocol):
    async def run(
        self,
        principal: Principal,
        *,
        subject: str,
        description: str,
    ) -> CustomerServiceWorkflowResult: ...


class CustomerServiceRepositoryPort(Protocol):
    async def create_ticket(self, ticket: CustomerTicket) -> CustomerTicket: ...

    async def list_visible_tickets(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
        status: CustomerTicketStatus | None,
        category: CustomerTicketCategory | None,
        limit: int,
        offset: int,
    ) -> list[CustomerTicket]: ...

    async def count_visible_tickets(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
        status: CustomerTicketStatus | None,
        category: CustomerTicketCategory | None,
    ) -> int: ...

    async def get_visible_detail(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
        ticket_id: UUID,
    ) -> tuple[CustomerTicket, ReplySuggestion | None] | None: ...

    async def classify_ticket(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        ticket_id: UUID,
        classification: TicketClassification,
    ) -> CustomerTicket: ...

    async def save_generated_suggestion(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        ticket_id: UUID,
        result: CustomerServiceWorkflowResult,
    ) -> tuple[CustomerTicket, ReplySuggestion]: ...

    async def confirm_suggestion(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        suggestion_id: UUID,
        final_reply: str | None,
    ) -> tuple[CustomerTicket, ReplySuggestion]: ...
