from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
from app.conversations.dependencies import get_conversation_service
from app.conversations.models import MessageRole
from app.conversations.schemas import (
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app


class FakeAuthenticationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate_access_token(self, access_token: str) -> Principal:
        if access_token != "access-token":
            raise AppError(code="invalid_token", message="令牌无效。", status_code=401)
        return self.principal


class FakeConversationService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.conversation = ConversationResponse(
            id=uuid4(),
            title="演示会话",
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        self.message = MessageResponse(
            id=uuid4(),
            position=1,
            role=MessageRole.USER,
            content="测试消息",
            metadata={},
            created_at=now,
        )
        self.deleted = False

    async def create(self, principal: Principal, request) -> ConversationResponse:
        return self.conversation.model_copy(update={"title": request.title or "新对话"})

    async def list(self, principal: Principal, *, limit: int, offset: int) -> ConversationListResponse:
        return ConversationListResponse(
            items=[] if self.deleted else [self.conversation],
            total=0 if self.deleted else 1,
            limit=limit,
            offset=offset,
        )

    async def get(self, principal: Principal, conversation_id: UUID) -> ConversationResponse:
        assert conversation_id == self.conversation.id
        return self.conversation

    async def list_messages(
        self,
        principal: Principal,
        conversation_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> MessageListResponse:
        assert conversation_id == self.conversation.id
        return MessageListResponse(items=[self.message], total=1, limit=limit, offset=offset)

    async def delete(self, principal: Principal, conversation_id: UUID) -> None:
        assert conversation_id == self.conversation.id
        self.deleted = True


def make_app():
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="demo",
        email="demo@example.com",
        roles=frozenset({"user"}),
    )
    auth = FakeAuthenticationService(principal)
    conversations = FakeConversationService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_conversation_service] = lambda: conversations
    return app, conversations


async def test_conversation_routes_follow_versioned_contract() -> None:
    app, service = make_app()
    headers = {"Authorization": "Bearer access-token"}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"title": " 新会话 "},
        )
        listed = await client.get(
            "/api/v1/conversations?limit=10&offset=0",
            headers=headers,
        )
        detail = await client.get(
            f"/api/v1/conversations/{service.conversation.id}",
            headers=headers,
        )
        messages = await client.get(
            f"/api/v1/conversations/{service.conversation.id}/messages?limit=50&offset=0",
            headers=headers,
        )
        deleted = await client.delete(
            f"/api/v1/conversations/{service.conversation.id}",
            headers=headers,
        )

    assert created.status_code == 201
    assert created.json()["title"] == "新会话"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["limit"] == 10
    assert detail.status_code == 200
    assert detail.json()["id"] == str(service.conversation.id)
    assert messages.status_code == 200
    assert messages.json()["items"][0]["position"] == 1
    assert messages.json()["items"][0]["role"] == "user"
    assert deleted.status_code == 204
    assert deleted.content == b""


async def test_conversation_pagination_is_validated() -> None:
    app, _ = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/conversations?limit=0&offset=-1",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
