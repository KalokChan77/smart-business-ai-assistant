from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx

from app.ai.dependencies import get_ai_chat_service
from app.ai.models import AIRunMode, AIRunStatus
from app.ai.schemas import AIRunResponse
from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
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


class FakeAIChatService:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.conversation_id = uuid4()
        self.request_id = None

    async def prepare(self, principal, request_id, request):
        self.request_id = request_id
        self.conversation_id = request.conversation_id
        return SimpleNamespace(run_id=self.run_id)

    async def stream(self, principal, prepared):
        yield 'event: metadata\ndata: {"run_id":"test-run"}\n\n'
        yield 'event: token\ndata: {"delta":"OK"}\n\n'
        yield 'event: message_end\ndata: {"message_id":"test-message"}\n\n'

    async def get_run(self, principal, run_id: UUID) -> AIRunResponse:
        assert run_id == self.run_id
        now = datetime.now(UTC)
        return AIRunResponse(
            id=run_id,
            conversation_id=self.conversation_id,
            request_id=self.request_id or "request-ai-api",
            provider="deepseek",
            model="deepseek-chat",
            mode=AIRunMode.CHAT,
            status=AIRunStatus.SUCCEEDED,
            prompt_message_id=uuid4(),
            response_message_id=uuid4(),
            input_tokens=2,
            output_tokens=1,
            error_code=None,
            started_at=now,
            completed_at=now,
            created_at=now,
            updated_at=now,
        )


def make_app():
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="demo",
        email="demo@example.com",
        roles=frozenset({"user"}),
    )
    auth = FakeAuthenticationService(principal)
    ai = FakeAIChatService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_ai_chat_service] = lambda: ai
    return app, ai


async def test_ai_stream_route_emits_versioned_sse_contract() -> None:
    app, service = make_app()
    conversation_id = uuid4()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/chat/stream",
            headers={
                "Authorization": "Bearer access-token",
                "X-Request-ID": "ai-api-request-1",
            },
            json={
                "conversation_id": str(conversation_id),
                "message": "只回复 OK",
                "provider": "deepseek",
            },
        )
        run = await client.get(
            f"/api/v1/ai/runs/{service.run_id}",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-request-id"] == "ai-api-request-1"
    assert [line for line in response.text.splitlines() if line.startswith("event:")] == [
        "event: metadata",
        "event: token",
        "event: message_end",
    ]
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"


async def test_ai_stream_request_is_validated_before_stream_start() -> None:
    app, _ = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/chat/stream",
            headers={"Authorization": "Bearer access-token"},
            json={"conversation_id": str(uuid4()), "message": "   "},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "validation_error"
