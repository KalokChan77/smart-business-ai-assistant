from datetime import date
from uuid import uuid4

import pytest

from app.ai.models import AIRunStatus
from app.analytics.ports import (
    AIErrorSummary,
    AIModelSummary,
    AIRunSummary,
    AnalyticsRepositoryError,
    CategorySummary,
    DailyConsultationSummary,
    SatisfactionSummary,
    TicketSummary,
    TopQuestionSummary,
)
from app.analytics.schemas import AnalyticsPeriodQuery
from app.analytics.service import AnalyticsService
from app.auth.principal import Principal
from app.core.errors import AppError
from app.customer_service.models import CustomerTicketCategory


class FakeAnalyticsRepository:
    def __init__(self, *, error: bool = False) -> None:
        self.error = error
        self.tenant_ids = []

    def _record(self, tenant_id) -> None:
        if self.error:
            raise AnalyticsRepositoryError
        self.tenant_ids.append(tenant_id)

    async def get_ticket_summary(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return TicketSummary(total=4, resolved=3, human_takeover=2)

    async def get_daily_consultations(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return (
            DailyConsultationSummary(
                day=date(2026, 7, 16),
                total=3,
                resolved=2,
                human_takeover=1,
            ),
        )

    async def get_category_distribution(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return (
            CategorySummary(
                category=CustomerTicketCategory.REFUND_AFTER_SALES,
                count=2,
            ),
            CategorySummary(category=None, count=1),
        )

    async def get_satisfaction_summary(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return SatisfactionSummary(total=3, positive=2, negative=1)

    async def get_top_questions(self, **kwargs):
        self._record(kwargs["tenant_id"])
        assert kwargs["limit"] == 5
        return (
            TopQuestionSummary(question="退款多久到账？", count=2),
        )

    async def get_ai_run_summary(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return AIRunSummary(
            total=5,
            running=1,
            succeeded=3,
            failed=1,
            cancelled=0,
            average_duration_ms=1234.567,
            average_input_tokens=100.555,
            average_output_tokens=200.444,
            by_model=(
                AIModelSummary(
                    provider="deepseek",
                    model="deepseek-chat",
                    total=4,
                    running=0,
                    succeeded=3,
                    failed=1,
                    cancelled=0,
                    average_duration_ms=1100.444,
                ),
                AIModelSummary(
                    provider="dashscope",
                    model="qwen-plus",
                    total=1,
                    running=1,
                    succeeded=0,
                    failed=0,
                    cancelled=0,
                    average_duration_ms=None,
                ),
            ),
            errors=(AIErrorSummary(code="provider_timeout", count=1),),
        )


class EmptyAnalyticsRepository(FakeAnalyticsRepository):
    async def get_ticket_summary(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return TicketSummary(total=0, resolved=0, human_takeover=0)

    async def get_daily_consultations(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return ()

    async def get_category_distribution(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return ()

    async def get_satisfaction_summary(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return SatisfactionSummary(total=0, positive=0, negative=0)

    async def get_top_questions(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return ()

    async def get_ai_run_summary(self, **kwargs):
        self._record(kwargs["tenant_id"])
        return AIRunSummary(
            total=0,
            running=0,
            succeeded=0,
            failed=0,
            cancelled=0,
            average_duration_ms=None,
            average_input_tokens=None,
            average_output_tokens=None,
            by_model=(),
            errors=(),
        )


def make_principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="decision",
        email="decision@example.com",
        roles=frozenset({"decision_maker"}),
    )


def period() -> AnalyticsPeriodQuery:
    return AnalyticsPeriodQuery(
        start_date=date(2026, 7, 15),
        end_date=date(2026, 7, 17),
    )


async def test_analytics_overview_uses_stable_metric_denominators() -> None:
    repository = FakeAnalyticsRepository()
    principal = make_principal()

    response = await AnalyticsService(repository).overview(principal, period())

    assert response.consultation_count == 4
    assert response.resolved_consultation_count == 3
    assert response.resolution_rate == 75.0
    assert response.human_takeover_rate == 50.0
    assert response.ai_run_count == 5
    assert response.ai_terminal_run_count == 4
    assert response.ai_success_rate == 75.0
    assert response.feedback_count == 3
    assert response.satisfaction_rate == 66.67
    assert response.top_questions[0].question == "退款多久到账？"
    assert len(response.summary_cards) == 4
    assert set(repository.tenant_ids) == {principal.tenant_id}


async def test_consultation_trend_fills_missing_utc_days_with_zero() -> None:
    response = await AnalyticsService(FakeAnalyticsRepository()).consultations(
        make_principal(),
        period(),
    )

    assert [point.date for point in response.points] == [
        date(2026, 7, 15),
        date(2026, 7, 16),
        date(2026, 7, 17),
    ]
    assert response.points[0].consultation_count == 0
    assert response.points[1].consultation_count == 3
    assert response.points[2].human_takeover_count == 0


async def test_category_distribution_returns_all_stable_categories() -> None:
    response = await AnalyticsService(FakeAnalyticsRepository()).categories(
        make_principal(),
        period(),
    )

    assert response.total == 3
    assert len(response.items) == 7
    assert [item.category for item in response.items] == [
        "refund_after_sales",
        "account_security",
        "product_service",
        "knowledge_document",
        "technical_support",
        "other",
        "unclassified",
    ]
    assert response.items[0].count == 2
    assert response.items[0].percentage == 66.67
    assert response.items[-1].count == 1
    assert response.items[-1].percentage == 33.33


async def test_satisfaction_and_ai_run_metrics_round_and_handle_running_runs() -> None:
    service = AnalyticsService(FakeAnalyticsRepository())
    principal = make_principal()

    satisfaction = await service.satisfaction(principal, period())
    ai_runs = await service.ai_runs(principal, period())

    assert satisfaction.model_dump()["satisfaction_rate"] == 66.67
    assert ai_runs.terminal == 4
    assert ai_runs.success_rate == 75.0
    assert ai_runs.average_duration_ms == 1234.57
    assert ai_runs.average_input_tokens == 100.56
    assert ai_runs.average_output_tokens == 200.44
    assert ai_runs.by_model[0].success_rate == 75.0
    assert ai_runs.by_model[1].terminal == 0
    assert ai_runs.by_model[1].success_rate == 0.0
    assert ai_runs.errors[0].code == "provider_timeout"


async def test_analytics_empty_period_returns_complete_zero_structures() -> None:
    service = AnalyticsService(EmptyAnalyticsRepository())
    principal = make_principal()

    overview = await service.overview(principal, period())
    consultations = await service.consultations(principal, period())
    categories = await service.categories(principal, period())
    satisfaction = await service.satisfaction(principal, period())
    ai_runs = await service.ai_runs(principal, period())

    assert overview.consultation_count == 0
    assert overview.resolution_rate == 0.0
    assert overview.ai_success_rate == 0.0
    assert overview.satisfaction_rate == 0.0
    assert overview.top_questions == []
    assert len(consultations.points) == 3
    assert all(point.consultation_count == 0 for point in consultations.points)
    assert categories.total == 0
    assert len(categories.items) == 7
    assert all(item.percentage == 0.0 for item in categories.items)
    assert satisfaction.feedback_count == 0
    assert ai_runs.total == 0
    assert ai_runs.average_duration_ms == 0.0


@pytest.mark.parametrize(
    "method_name",
    ["overview", "consultations", "categories", "satisfaction", "ai_runs"],
)
async def test_analytics_service_maps_repository_failure(method_name: str) -> None:
    service = AnalyticsService(FakeAnalyticsRepository(error=True))
    method = getattr(service, method_name)

    with pytest.raises(AppError) as captured:
        await method(make_principal(), period())

    assert captured.value.status_code == 503
    assert captured.value.code == "analytics_unavailable"
    assert "database" not in captured.value.message.lower()
