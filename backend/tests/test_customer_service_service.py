from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.auth.principal import Principal
from app.core.errors import AppError
from app.customer_service.classification import RuleBasedTicketClassifier
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
from app.customer_service.ports import (
    CustomerServiceKnowledgeResult,
    CustomerServiceWorkflowResult,
    CustomerTicketNotActionableError,
    ReplySuggestionAlreadyConfirmedError,
    TicketClassification,
)
from app.customer_service.schemas import (
    CustomerTicketCreateRequest,
    ReplySuggestionConfirmRequest,
)
from app.customer_service.service import CustomerService


def make_principal(*roles: str) -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="customer-service-test",
        email="customer-service-test@example.test",
        roles=frozenset(roles),
    )


def make_ticket(principal: Principal) -> CustomerTicket:
    now = datetime.now(UTC)
    ticket = CustomerTicket(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        requester_user_id=principal.user_id,
        subject="退款问题",
        description="退款什么时候到账？",
        status=CustomerTicketStatus.OPEN,
        priority=CustomerTicketPriority.NORMAL,
    )
    ticket.created_at = now
    ticket.updated_at = now
    return ticket


def make_suggestion(ticket: CustomerTicket, actor_id: UUID) -> ReplySuggestion:
    now = datetime.now(UTC)
    suggestion = ReplySuggestion(
        id=uuid4(),
        ticket_id=ticket.id,
        tenant_id=ticket.tenant_id,
        category=CustomerTicketCategory.REFUND_AFTER_SALES,
        status=ReplySuggestionStatus.DRAFT,
        suggested_reply="建议回复",
        knowledge_outcome=CustomerServiceKnowledgeOutcome.ANSWERED,
        citations=[],
        quality_status=ReplyQualityStatus.PASSED,
        quality_notes=[],
        workflow_version="customer-service-v1",
        generated_by_user_id=actor_id,
    )
    suggestion.created_at = now
    suggestion.updated_at = now
    return suggestion


class FakeWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, principal, *, subject, description):
        self.calls.append((subject, description))
        return CustomerServiceWorkflowResult(
            classification=TicketClassification(
                category=CustomerTicketCategory.REFUND_AFTER_SALES,
                priority=CustomerTicketPriority.HIGH,
                confidence=90,
                reason="退款分类",
            ),
            suggested_reply="建议回复",
            knowledge=CustomerServiceKnowledgeResult(
                outcome=CustomerServiceKnowledgeOutcome.ANSWERED,
                answer="知识回答",
                citations=(),
            ),
            quality_status=ReplyQualityStatus.PASSED,
            quality_notes=(),
            workflow_version="customer-service-v1",
        )


class FakeRepository:
    def __init__(self, principal: Principal) -> None:
        self.ticket = make_ticket(principal)
        self.suggestion: ReplySuggestion | None = None
        self.last_staff: bool | None = None
        self.classify_error: Exception | None = None
        self.save_error: Exception | None = None

    async def create_ticket(self, ticket):
        ticket.id = uuid4()
        ticket.created_at = datetime.now(UTC)
        ticket.updated_at = ticket.created_at
        self.ticket = ticket
        return ticket

    async def list_visible_tickets(self, **kwargs):
        self.last_staff = kwargs["staff"]
        return [self.ticket]

    async def count_visible_tickets(self, **kwargs):
        return 1

    async def get_visible_detail(self, **kwargs):
        self.last_staff = kwargs["staff"]
        if (
            not kwargs["staff"]
            and self.suggestion is not None
            and self.suggestion.status == ReplySuggestionStatus.DRAFT
        ):
            return self.ticket, None
        return self.ticket, self.suggestion

    async def classify_ticket(self, **kwargs):
        if self.classify_error:
            raise self.classify_error
        classification = kwargs["classification"]
        self.ticket.category = classification.category
        self.ticket.priority = classification.priority
        self.ticket.classification_confidence = classification.confidence
        self.ticket.classification_reason = classification.reason
        self.ticket.assigned_user_id = kwargs["actor_user_id"]
        self.ticket.status = CustomerTicketStatus.IN_PROGRESS
        return self.ticket

    async def save_generated_suggestion(self, **kwargs):
        if self.save_error:
            raise self.save_error
        self.suggestion = make_suggestion(self.ticket, kwargs["actor_user_id"])
        return self.ticket, self.suggestion

    async def confirm_suggestion(self, **kwargs):
        if self.suggestion is None:
            self.suggestion = make_suggestion(self.ticket, kwargs["actor_user_id"])
        self.suggestion.status = ReplySuggestionStatus.CONFIRMED
        self.suggestion.final_reply = kwargs["final_reply"] or self.suggestion.suggested_reply
        self.suggestion.confirmed_by_user_id = kwargs["actor_user_id"]
        self.suggestion.confirmed_at = datetime.now(UTC)
        self.ticket.status = CustomerTicketStatus.RESOLVED
        self.ticket.resolved_at = self.suggestion.confirmed_at
        return self.ticket, self.suggestion


def build_service(principal: Principal):
    repository = FakeRepository(principal)
    workflow = FakeWorkflow()
    return (
        CustomerService(
            repository=repository,
            classifier=RuleBasedTicketClassifier(),
            workflow=workflow,
        ),
        repository,
        workflow,
    )


async def test_service_creates_owned_ticket_and_scopes_lists_by_role() -> None:
    user = make_principal("user")
    service, repository, _ = build_service(user)

    created = await service.create_ticket(
        user,
        CustomerTicketCreateRequest(subject=" 退款 ", description=" 退款多久到账？ "),
    )
    listed = await service.list_tickets(
        user,
        status_filter=None,
        category_filter=None,
        limit=20,
        offset=0,
    )

    assert repository.ticket.requester_user_id == user.user_id
    assert created.subject == "退款"
    assert "requester_user_id" not in created.model_dump()
    assert "tenant_id" not in created.model_dump()
    assert listed.total == 1
    assert repository.last_staff is False

    staff = Principal(
        user_id=uuid4(),
        tenant_id=user.tenant_id,
        username="staff",
        email="staff@example.test",
        roles=frozenset({"customer_service"}),
    )
    await service.list_tickets(
        staff,
        status_filter=None,
        category_filter=None,
        limit=20,
        offset=0,
    )
    assert repository.last_staff is True


async def test_service_separates_requester_and_staff_ticket_views() -> None:
    requester = make_principal("user")
    service, repository, _ = build_service(requester)
    repository.suggestion = make_suggestion(repository.ticket, uuid4())

    public_detail = await service.get_ticket(requester, repository.ticket.id)

    assert public_detail.view == "public"
    assert public_detail.confirmed_reply is None
    assert "reply_suggestion" not in public_detail.model_dump()
    assert "requester_user_id" not in public_detail.ticket.model_dump()

    staff = Principal(
        user_id=uuid4(),
        tenant_id=requester.tenant_id,
        username="staff-detail",
        email="staff-detail@example.test",
        roles=frozenset({"customer_service"}),
    )
    internal_detail = await service.get_ticket(staff, repository.ticket.id)

    assert internal_detail.view == "internal"
    assert internal_detail.reply_suggestion is not None
    assert internal_detail.reply_suggestion.suggested_reply == "建议回复"
    assert internal_detail.ticket.requester_user_id == requester.user_id


async def test_service_exposes_only_confirmed_final_reply_to_requester() -> None:
    requester = make_principal("user")
    service, repository, _ = build_service(requester)
    suggestion = make_suggestion(repository.ticket, uuid4())
    suggestion.status = ReplySuggestionStatus.CONFIRMED
    suggestion.final_reply = "人工确认后的公开回复"
    suggestion.confirmed_by_user_id = uuid4()
    suggestion.confirmed_at = datetime.now(UTC)
    repository.suggestion = suggestion
    repository.ticket.status = CustomerTicketStatus.RESOLVED
    repository.ticket.resolved_at = suggestion.confirmed_at

    detail = await service.get_ticket(requester, repository.ticket.id)

    assert detail.view == "public"
    assert detail.confirmed_reply is not None
    assert detail.confirmed_reply.final_reply == "人工确认后的公开回复"
    payload = detail.model_dump()
    assert "reply_suggestion" not in payload
    assert "confirmed_by_user_id" not in str(payload)
    assert "workflow_version" not in str(payload)
    assert "quality_notes" not in str(payload)


async def test_service_generates_and_confirms_human_reply() -> None:
    staff = make_principal("customer_service")
    service, repository, workflow = build_service(staff)

    generated = await service.generate_suggestion(staff, repository.ticket.id)
    confirmed = await service.confirm_suggestion(
        staff,
        generated.id,
        ReplySuggestionConfirmRequest(final_reply="人工编辑后的回复"),
    )

    assert workflow.calls == [("退款问题", "退款什么时候到账？")]
    assert generated.status == ReplySuggestionStatus.DRAFT
    assert confirmed.ticket.status == CustomerTicketStatus.RESOLVED
    assert confirmed.reply_suggestion is not None
    assert confirmed.reply_suggestion.final_reply == "人工编辑后的回复"


@pytest.mark.parametrize(
    ("repository_error", "expected_code"),
    [
        (CustomerTicketNotActionableError(), "customer_ticket_not_actionable"),
        (
            ReplySuggestionAlreadyConfirmedError(),
            "reply_suggestion_already_confirmed",
        ),
    ],
)
async def test_service_maps_generation_state_errors(
    repository_error: Exception,
    expected_code: str,
) -> None:
    staff = make_principal("admin")
    service, repository, _ = build_service(staff)
    repository.save_error = repository_error

    with pytest.raises(AppError) as captured:
        await service.generate_suggestion(staff, repository.ticket.id)

    assert captured.value.code == expected_code
