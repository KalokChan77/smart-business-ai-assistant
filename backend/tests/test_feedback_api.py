from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import AppError
from app.feedback.dependencies import get_feedback_service
from app.feedback.models import FeedbackRating
from app.feedback.schemas import AIFeedbackResponse
from app.main import create_app


class FakeAuthenticationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate_access_token(self, access_token: str) -> Principal:
        if access_token != "access-token":
            raise AppError(code="invalid_token", message="令牌无效。", status_code=401)
        return self.principal


class FakeFeedbackService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, FeedbackRating, str | None]] = []
        self.feedback_id = uuid4()
        self.message_id = uuid4()

    async def submit(self, principal, run_id, payload) -> AIFeedbackResponse:
        self.calls.append(
            (
                principal.user_id,
                run_id,
                payload.rating,
                payload.comment,
            )
        )
        now = datetime.now(UTC)
        return AIFeedbackResponse(
            id=self.feedback_id,
            run_id=run_id,
            message_id=self.message_id,
            rating=payload.rating,
            comment=payload.comment,
            created_at=now,
            updated_at=now,
        )


def make_app():
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="feedback-api-user",
        email="feedback-api-user@example.test",
        roles=frozenset({"user"}),
    )
    auth = FakeAuthenticationService(principal)
    feedback = FakeFeedbackService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_feedback_service] = lambda: feedback
    return app, principal, feedback


async def test_feedback_route_returns_public_upserted_feedback() -> None:
    app, principal, service = make_app()
    run_id = uuid4()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/ai/runs/{run_id}/feedback",
            headers={"Authorization": "Bearer access-token"},
            json={
                "rating": "negative",
                "comment": "  回答不够完整。  ",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(service.feedback_id)
    assert body["run_id"] == str(run_id)
    assert body["message_id"] == str(service.message_id)
    assert body["rating"] == "negative"
    assert body["comment"] == "回答不够完整。"
    assert "tenant_id" not in body
    assert "user_id" not in body
    assert service.calls == [
        (
            principal.user_id,
            run_id,
            FeedbackRating.NEGATIVE,
            "回答不够完整。",
        )
    ]


async def test_feedback_route_normalizes_empty_comment_to_null() -> None:
    app, _, service = make_app()
    run_id = uuid4()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/ai/runs/{run_id}/feedback",
            headers={"Authorization": "Bearer access-token"},
            json={"rating": "positive", "comment": "   "},
        )

    assert response.status_code == 200
    assert response.json()["comment"] is None
    assert service.calls[0][3] is None


async def test_feedback_route_requires_authentication() -> None:
    app, _, service = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/ai/runs/{uuid4()}/feedback",
            json={"rating": "positive"},
        )

    assert response.status_code == 401
    assert service.calls == []


async def test_feedback_route_rejects_client_controlled_associations() -> None:
    app, _, service = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/ai/runs/{uuid4()}/feedback",
            headers={"Authorization": "Bearer access-token"},
            json={
                "rating": "negative",
                "message_id": str(uuid4()),
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


async def test_feedback_route_uses_unified_validation_errors() -> None:
    app, _, service = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"Authorization": "Bearer access-token"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        invalid_path = await client.post(
            "/api/v1/ai/runs/not-a-uuid/feedback",
            headers=headers,
            json={"rating": "positive"},
        )
        invalid_rating = await client.post(
            f"/api/v1/ai/runs/{uuid4()}/feedback",
            headers=headers,
            json={"rating": "neutral"},
        )
        long_comment = await client.post(
            f"/api/v1/ai/runs/{uuid4()}/feedback",
            headers=headers,
            json={"rating": "negative", "comment": "x" * 1001},
        )

    for response in (invalid_path, invalid_rating, long_comment):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


async def test_feedback_comment_length_is_checked_after_trimming() -> None:
    app, _, service = make_app()
    run_id = uuid4()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/ai/runs/{run_id}/feedback",
            headers={"Authorization": "Bearer access-token"},
            json={"rating": "negative", "comment": f"  {'x' * 1000}  "},
        )

    assert response.status_code == 200
    assert service.calls[0][3] == "x" * 1000
