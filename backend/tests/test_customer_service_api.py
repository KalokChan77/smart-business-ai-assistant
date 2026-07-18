from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import AppError
from app.customer_service.dependencies import get_customer_service
from app.customer_service.models import (
    CustomerServiceKnowledgeOutcome,
    CustomerTicketCategory,
    CustomerTicketPriority,
    CustomerTicketStatus,
    ReplyQualityStatus,
    ReplySuggestionStatus,
)
from app.customer_service.schemas import (
    CustomerTicketClassificationResponse,
    CustomerTicketInternalDetailResponse,
    CustomerTicketInternalResponse,
    CustomerTicketListResponse,
    CustomerTicketPublicDetailResponse,
    CustomerTicketPublicResponse,
    ReplySuggestionResponse,
)
from app.main import create_app


class FakeAuthenticationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate_access_token(self, access_token: str) -> Principal:
        if access_token != "access-token":
            raise AppError(code="invalid_token", message="令牌无效。", status_code=401)
        return self.principal


class FakeCustomerService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.ticket_id = uuid4()
        self.suggestion_id = uuid4()
        self.calls: list[tuple] = []

    def ticket_response(self, *, status=CustomerTicketStatus.OPEN):
        now = datetime.now(UTC)
        return CustomerTicketPublicResponse(
            id=self.ticket_id,
            subject="退款到账时间",
            description="退款多久到账？",
            status=status,
            category=None,
            priority=CustomerTicketPriority.NORMAL,
            resolved_at=None,
            created_at=now,
            updated_at=now,
        )

    def internal_ticket_response(self, *, status=CustomerTicketStatus.OPEN):
        public = self.ticket_response(status=status)
        return CustomerTicketInternalResponse(
            **public.model_dump(),
            requester_user_id=self.principal.user_id,
            assigned_user_id=None,
            classification_confidence=None,
            classification_reason=None,
        )

    def suggestion_response(self, *, status=ReplySuggestionStatus.DRAFT):
        now = datetime.now(UTC)
        return ReplySuggestionResponse(
            id=self.suggestion_id,
            ticket_id=self.ticket_id,
            status=status,
            category=CustomerTicketCategory.REFUND_AFTER_SALES,
            suggested_reply="建议回复",
            final_reply=None if status == ReplySuggestionStatus.DRAFT else "最终回复",
            knowledge_outcome=CustomerServiceKnowledgeOutcome.ANSWERED,
            citations=[],
            quality_status=ReplyQualityStatus.PASSED,
            quality_notes=[],
            workflow_version="customer-service-v1",
            generated_by_user_id=self.principal.user_id,
            confirmed_by_user_id=None,
            confirmed_at=None,
            created_at=now,
            updated_at=now,
        )

    async def create_ticket(self, principal, payload):
        self.calls.append(("create", payload.subject, payload.description))
        response = self.ticket_response()
        response.subject = payload.subject
        response.description = payload.description
        return response

    async def list_tickets(self, principal, **kwargs):
        self.calls.append(("list", kwargs))
        return CustomerTicketListResponse(
            items=[self.ticket_response()],
            total=1,
            limit=kwargs["limit"],
            offset=kwargs["offset"],
        )

    async def get_ticket(self, principal, ticket_id):
        self.calls.append(("get", ticket_id))
        if principal.roles.isdisjoint({"customer_service", "admin"}):
            return CustomerTicketPublicDetailResponse(
                ticket=self.ticket_response(),
                confirmed_reply=None,
            )
        return CustomerTicketInternalDetailResponse(
            ticket=self.internal_ticket_response(),
            reply_suggestion=self.suggestion_response(),
        )

    async def classify_ticket(self, principal, ticket_id):
        self.calls.append(("classify", ticket_id))
        return CustomerTicketClassificationResponse(
            ticket_id=ticket_id,
            category=CustomerTicketCategory.REFUND_AFTER_SALES,
            priority=CustomerTicketPriority.HIGH,
            confidence=90,
            reason="退款分类",
            status=CustomerTicketStatus.IN_PROGRESS,
            assigned_user_id=principal.user_id,
        )

    async def generate_suggestion(self, principal, ticket_id):
        self.calls.append(("generate", ticket_id))
        return self.suggestion_response()

    async def confirm_suggestion(self, principal, suggestion_id, payload):
        self.calls.append(("confirm", suggestion_id, payload.final_reply))
        suggestion = self.suggestion_response(status=ReplySuggestionStatus.CONFIRMED)
        suggestion.final_reply = payload.final_reply or suggestion.suggested_reply
        suggestion.confirmed_by_user_id = principal.user_id
        suggestion.confirmed_at = datetime.now(UTC)
        ticket = self.internal_ticket_response(status=CustomerTicketStatus.RESOLVED)
        ticket.resolved_at = suggestion.confirmed_at
        return CustomerTicketInternalDetailResponse(
            ticket=ticket,
            reply_suggestion=suggestion,
        )


def make_app(*roles: str):
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="customer-service-api",
        email="customer-service-api@example.test",
        roles=frozenset(roles),
    )
    auth = FakeAuthenticationService(principal)
    service = FakeCustomerService(principal)
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_customer_service] = lambda: service
    return app, principal, service


async def test_ticket_create_normalizes_and_rejects_server_fields() -> None:
    app, _, service = make_app("user")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/customer-service/tickets",
            headers={"Authorization": "Bearer access-token"},
            json={"subject": " 退款 ", "description": " 退款多久到账？ "},
        )
        rejected = await client.post(
            "/api/v1/customer-service/tickets",
            headers={"Authorization": "Bearer access-token"},
            json={
                "subject": "退款",
                "description": "退款多久到账？",
                "tenant_id": str(uuid4()),
            },
        )

    assert created.status_code == 201
    assert created.json()["subject"] == "退款"
    assert service.calls[0] == ("create", "退款", "退款多久到账？")
    assert rejected.status_code == 422


async def test_staff_can_classify_generate_and_confirm() -> None:
    app, _, service = make_app("customer_service")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"Authorization": "Bearer access-token"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        classified = await client.post(
            "/api/v1/customer-service/classify",
            headers=headers,
            json={"ticket_id": str(service.ticket_id)},
        )
        generated = await client.post(
            "/api/v1/customer-service/reply-suggestions",
            headers=headers,
            json={"ticket_id": str(service.ticket_id)},
        )
        confirmed = await client.post(
            f"/api/v1/customer-service/reply-suggestions/{service.suggestion_id}/confirm",
            headers=headers,
            json={"final_reply": "  人工确认回复  "},
        )

    assert classified.status_code == 200
    assert classified.json()["category"] == "refund_after_sales"
    assert generated.status_code == 200
    assert generated.json()["status"] == "draft"
    assert confirmed.status_code == 200
    assert confirmed.json()["ticket"]["status"] == "resolved"
    assert confirmed.json()["reply_suggestion"]["final_reply"] == "人工确认回复"


async def test_normal_user_is_forbidden_from_staff_operations() -> None:
    app, _, service = make_app("user")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/customer-service/classify",
            headers={"Authorization": "Bearer access-token"},
            json={"ticket_id": str(service.ticket_id)},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert service.calls == []


async def test_requester_detail_hides_internal_draft_and_actor_ids() -> None:
    app, _, service = make_app("user")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/customer-service/tickets/{service.ticket_id}",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["view"] == "public"
    assert payload["confirmed_reply"] is None
    assert "reply_suggestion" not in payload
    assert "tenant_id" not in payload["ticket"]
    assert "requester_user_id" not in payload["ticket"]
    assert "assigned_user_id" not in payload["ticket"]


async def test_customer_service_routes_require_authentication() -> None:
    app, _, service = make_app("customer_service")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/customer-service/tickets")

    assert response.status_code == 401
    assert service.calls == []


async def test_confirm_rejects_blank_or_extra_fields() -> None:
    app, _, service = make_app("admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"Authorization": "Bearer access-token"}
    url = f"/api/v1/customer-service/reply-suggestions/{service.suggestion_id}/confirm"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        blank = await client.post(url, headers=headers, json={"final_reply": "   "})
        extra = await client.post(
            url,
            headers=headers,
            json={"final_reply": "确认", "send_automatically": True},
        )

    assert blank.status_code == 422
    assert extra.status_code == 422
    assert service.calls == []
