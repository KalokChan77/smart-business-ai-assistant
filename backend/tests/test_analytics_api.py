from datetime import date
from uuid import uuid4

import httpx
import pytest

from app.analytics.dependencies import get_analytics_service
from app.analytics.schemas import (
    AIErrorMetrics,
    AIRunMetricsResponse,
    AnalyticsOverviewResponse,
    AnalyticsPeriodResponse,
    AnalyticsSummaryCard,
    CategoryDistributionItem,
    CategoryDistributionResponse,
    ConsultationTrendPoint,
    ConsultationTrendResponse,
    SatisfactionResponse,
)
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


class FakeAnalyticsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    @staticmethod
    def _period(period) -> AnalyticsPeriodResponse:
        return AnalyticsPeriodResponse(
            start_date=period.start_date,
            end_date=period.end_date,
        )

    async def overview(self, principal, period):
        self.calls.append(("overview", principal, period))
        return AnalyticsOverviewResponse(
            period=self._period(period),
            consultation_count=1,
            resolved_consultation_count=1,
            resolution_rate=100.0,
            human_takeover_count=1,
            human_takeover_rate=100.0,
            ai_run_count=1,
            ai_terminal_run_count=1,
            ai_success_rate=100.0,
            feedback_count=1,
            positive_feedback_count=1,
            satisfaction_rate=100.0,
            top_questions=[],
            summary_cards=[
                AnalyticsSummaryCard(
                    code="consultation_volume",
                    title="咨询量",
                    value="1",
                    description="测试摘要。",
                )
            ],
        )

    async def consultations(self, principal, period):
        self.calls.append(("consultations", principal, period))
        return ConsultationTrendResponse(
            period=self._period(period),
            points=[
                ConsultationTrendPoint(
                    date=period.start_date,
                    consultation_count=1,
                    resolved_count=1,
                    human_takeover_count=1,
                )
            ],
        )

    async def categories(self, principal, period):
        self.calls.append(("categories", principal, period))
        return CategoryDistributionResponse(
            period=self._period(period),
            total=1,
            items=[
                CategoryDistributionItem(
                    category="other",
                    count=1,
                    percentage=100.0,
                )
            ],
        )

    async def satisfaction(self, principal, period):
        self.calls.append(("satisfaction", principal, period))
        return SatisfactionResponse(
            period=self._period(period),
            feedback_count=1,
            positive_count=1,
            negative_count=0,
            satisfaction_rate=100.0,
        )

    async def ai_runs(self, principal, period):
        self.calls.append(("ai_runs", principal, period))
        return AIRunMetricsResponse(
            period=self._period(period),
            total=1,
            running=0,
            succeeded=1,
            failed=0,
            cancelled=0,
            terminal=1,
            success_rate=100.0,
            average_duration_ms=100.0,
            average_input_tokens=10.0,
            average_output_tokens=20.0,
            by_model=[],
            errors=[AIErrorMetrics(code="none", count=1)],
        )


def make_app(role: str):
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="analytics-user",
        email="analytics@example.com",
        roles=frozenset({role}),
    )
    auth = FakeAuthenticationService(principal)
    analytics = FakeAnalyticsService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_analytics_service] = lambda: analytics
    return app, analytics, principal


@pytest.mark.parametrize("role", ["admin", "decision_maker"])
async def test_analytics_routes_allow_admin_and_decision_maker(role: str) -> None:
    app, service, principal = make_app(role)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    paths = [
        "/api/v1/analytics/overview",
        "/api/v1/analytics/consultations",
        "/api/v1/analytics/categories",
        "/api/v1/analytics/satisfaction",
        "/api/v1/analytics/ai-runs",
    ]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [
            await client.get(
                path,
                headers={"Authorization": "Bearer access-token"},
                params={
                    "start_date": "2026-07-15",
                    "end_date": "2026-07-17",
                },
            )
            for path in paths
        ]

    assert [response.status_code for response in responses] == [200] * 5
    assert len(service.calls) == 5
    assert all(call[1] == principal for call in service.calls)
    assert all(call[2].start_date == date(2026, 7, 15) for call in service.calls)
    assert all(call[2].end_date == date(2026, 7, 17) for call in service.calls)


@pytest.mark.parametrize("role", ["user", "customer_service"])
async def test_analytics_routes_reject_non_reporting_roles(role: str) -> None:
    app, service, _ = make_app(role)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/analytics/overview",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert service.calls == []


async def test_analytics_routes_require_authentication() -> None:
    app, service, _ = make_app("admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/overview")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert service.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-07-18", "end_date": "2026-07-17"},
        {"start_date": "2025-07-16", "end_date": "2026-07-17"},
        {"start_date": "not-a-date"},
        {"unknown": "sensitive-marker"},
    ],
)
async def test_analytics_routes_reject_invalid_or_extra_query_params(params) -> None:
    app, service, _ = make_app("admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/analytics/overview",
            headers={"Authorization": "Bearer access-token"},
            params=params,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "sensitive-marker" not in response.text
    assert service.calls == []
