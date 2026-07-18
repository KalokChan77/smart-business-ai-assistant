from uuid import uuid4

import httpx
import pytest

from app.audio.dependencies import get_audio_service
from app.audio.ports import SynthesizedAudio
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


class FakeAudioService:
    def __init__(self) -> None:
        self.principal: Principal | None = None
        self.text: str | None = None

    async def synthesize(self, principal, request) -> SynthesizedAudio:
        self.principal = principal
        self.text = request.text
        return SynthesizedAudio(
            content=b"RIFF-platform-audio",
            media_type="audio/wav",
        )


def make_app(*, roles=frozenset({"user"})):
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="demo",
        email="demo@example.com",
        roles=roles,
    )
    auth = FakeAuthenticationService(principal)
    audio = FakeAudioService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_audio_service] = lambda: audio
    return app, audio, principal


@pytest.mark.parametrize(
    "roles",
    [
        frozenset({"user"}),
        frozenset({"customer_service"}),
        frozenset({"decision_maker"}),
        frozenset({"admin"}),
    ],
)
async def test_tts_route_allows_every_authenticated_role(roles) -> None:
    app, service, principal = make_app(roles=roles)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/audio/tts",
            headers={
                "Authorization": "Bearer access-token",
                "X-Request-ID": "audio-api-request-1",
            },
            json={"text": "  退款申请已经进入审核流程。  "},
        )

    assert response.status_code == 200
    assert response.content == b"RIFF-platform-audio"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"] == "audio-api-request-1"
    assert service.principal == principal
    assert service.text == "退款申请已经进入审核流程。"


async def test_tts_route_requires_bearer_token() -> None:
    app, service, _ = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/audio/tts",
            json={"text": "语音测试"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert service.text is None


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "   "},
        {"text": "字" * 501},
        {"text": 123},
        {"text": "语音测试", "voice": "sensitive-marker"},
        {"text": "语音测试", "user": "sensitive-marker"},
        {"text": "语音测试", "api_key": "sensitive-marker"},
    ],
)
async def test_tts_route_rejects_invalid_or_internal_fields(payload) -> None:
    app, service, _ = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/audio/tts",
            headers={"Authorization": "Bearer access-token"},
            json=payload,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "sensitive-marker" not in response.text
    assert service.text is None
