from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.agent.dependencies import get_agent_service
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


class FakeAgentService:
    def __init__(self) -> None:
        self.request_id: str | None = None
        self.request = None

    async def prepare(self, principal, request_id, request):
        self.request_id = request_id
        self.request = request
        return SimpleNamespace(run_id=uuid4())

    async def stream(self, principal, prepared):
        yield 'event: metadata\ndata: {"mode":"agent"}\n\n'
        yield 'event: tool_start\ndata: {"tool":"calculate_business_metric"}\n\n'
        yield 'event: tool_end\ndata: {"output":"100"}\n\n'
        yield 'event: token\ndata: {"delta":"计算结果是 100。"}\n\n'
        yield 'event: message_end\ndata: {"tool_call_count":1}\n\n'


def make_app():
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="demo",
        email="demo@example.com",
        roles=frozenset({"user"}),
    )
    auth = FakeAuthenticationService(principal)
    agent = FakeAgentService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_agent_service] = lambda: agent
    return app, agent


async def test_agent_stream_route_emits_tool_aware_sse_contract() -> None:
    app, service = make_app()
    conversation_id = uuid4()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/agent/stream",
            headers={
                "Authorization": "Bearer access-token",
                "X-Request-ID": "agent-api-request-1",
            },
            json={
                "conversation_id": str(conversation_id),
                "message": "请计算 12 * 8 + 4",
                "provider": "deepseek",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-request-id"] == "agent-api-request-1"
    assert [line for line in response.text.splitlines() if line.startswith("event:")] == [
        "event: metadata",
        "event: tool_start",
        "event: tool_end",
        "event: token",
        "event: message_end",
    ]
    assert service.request_id == "agent-api-request-1"
    assert service.request.conversation_id == conversation_id
    assert service.request.provider == "deepseek"


async def test_agent_stream_request_is_validated_before_stream_start() -> None:
    app, _ = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/agent/stream",
            headers={"Authorization": "Bearer access-token"},
            json={"conversation_id": str(uuid4()), "message": "   "},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "validation_error"
