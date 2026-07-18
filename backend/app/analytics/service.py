from datetime import UTC, date, datetime, time, timedelta

from fastapi import status

from app.analytics.ports import (
    AIRunSummary,
    AnalyticsRepository,
    AnalyticsRepositoryError,
    SatisfactionSummary,
    TicketSummary,
)
from app.analytics.schemas import (
    AIErrorMetrics,
    AIModelMetrics,
    AIRunMetricsResponse,
    AnalyticsOverviewResponse,
    AnalyticsPeriodQuery,
    AnalyticsPeriodResponse,
    AnalyticsSummaryCard,
    CategoryDistributionItem,
    CategoryDistributionResponse,
    ConsultationTrendPoint,
    ConsultationTrendResponse,
    SatisfactionResponse,
    TopQuestionResponse,
)
from app.auth.principal import Principal
from app.core.errors import AppError
from app.customer_service.models import CustomerTicketCategory

_CATEGORY_ORDER: tuple[CustomerTicketCategory | None, ...] = (
    CustomerTicketCategory.REFUND_AFTER_SALES,
    CustomerTicketCategory.ACCOUNT_SECURITY,
    CustomerTicketCategory.PRODUCT_SERVICE,
    CustomerTicketCategory.KNOWLEDGE_DOCUMENT,
    CustomerTicketCategory.TECHNICAL_SUPPORT,
    CustomerTicketCategory.OTHER,
    None,
)


class AnalyticsService:
    """Apply stable metric definitions to tenant-scoped aggregate facts."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    async def overview(
        self,
        principal: Principal,
        period: AnalyticsPeriodQuery,
    ) -> AnalyticsOverviewResponse:
        start_at, end_at = self._bounds(period)
        try:
            tickets = await self._repository.get_ticket_summary(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
            ai_runs = await self._repository.get_ai_run_summary(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
            feedback = await self._repository.get_satisfaction_summary(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
            top_questions = await self._repository.get_top_questions(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
                limit=5,
            )
        except AnalyticsRepositoryError as exc:
            raise self._unavailable_error() from exc

        ai_terminal = self._terminal_count(ai_runs)
        resolution_rate = self._percentage(tickets.resolved, tickets.total)
        takeover_rate = self._percentage(tickets.human_takeover, tickets.total)
        ai_success_rate = self._percentage(ai_runs.succeeded, ai_terminal)
        satisfaction_rate = self._percentage(feedback.positive, feedback.total)
        return AnalyticsOverviewResponse(
            period=self._period_response(period),
            consultation_count=tickets.total,
            resolved_consultation_count=tickets.resolved,
            resolution_rate=resolution_rate,
            human_takeover_count=tickets.human_takeover,
            human_takeover_rate=takeover_rate,
            ai_run_count=ai_runs.total,
            ai_terminal_run_count=ai_terminal,
            ai_success_rate=ai_success_rate,
            feedback_count=feedback.total,
            positive_feedback_count=feedback.positive,
            satisfaction_rate=satisfaction_rate,
            top_questions=[
                TopQuestionResponse(
                    question=item.question[:120],
                    count=item.count,
                )
                for item in top_questions
            ],
            summary_cards=self._summary_cards(
                tickets=tickets,
                ai_runs=ai_runs,
                feedback=feedback,
            ),
        )

    async def consultations(
        self,
        principal: Principal,
        period: AnalyticsPeriodQuery,
    ) -> ConsultationTrendResponse:
        start_at, end_at = self._bounds(period)
        try:
            rows = await self._repository.get_daily_consultations(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
        except AnalyticsRepositoryError as exc:
            raise self._unavailable_error() from exc
        by_day = {item.day: item for item in rows}
        assert period.start_date is not None and period.end_date is not None
        points: list[ConsultationTrendPoint] = []
        current = period.start_date
        while current <= period.end_date:
            item = by_day.get(current)
            points.append(
                ConsultationTrendPoint(
                    date=current,
                    consultation_count=item.total if item else 0,
                    resolved_count=item.resolved if item else 0,
                    human_takeover_count=item.human_takeover if item else 0,
                )
            )
            current += timedelta(days=1)
        return ConsultationTrendResponse(
            period=self._period_response(period),
            points=points,
        )

    async def categories(
        self,
        principal: Principal,
        period: AnalyticsPeriodQuery,
    ) -> CategoryDistributionResponse:
        start_at, end_at = self._bounds(period)
        try:
            rows = await self._repository.get_category_distribution(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
        except AnalyticsRepositoryError as exc:
            raise self._unavailable_error() from exc
        counts = {item.category: item.count for item in rows}
        total = sum(counts.values())
        return CategoryDistributionResponse(
            period=self._period_response(period),
            total=total,
            items=[
                CategoryDistributionItem(
                    category=category.value if category else "unclassified",
                    count=counts.get(category, 0),
                    percentage=self._percentage(counts.get(category, 0), total),
                )
                for category in _CATEGORY_ORDER
            ],
        )

    async def satisfaction(
        self,
        principal: Principal,
        period: AnalyticsPeriodQuery,
    ) -> SatisfactionResponse:
        start_at, end_at = self._bounds(period)
        try:
            summary = await self._repository.get_satisfaction_summary(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
        except AnalyticsRepositoryError as exc:
            raise self._unavailable_error() from exc
        return SatisfactionResponse(
            period=self._period_response(period),
            feedback_count=summary.total,
            positive_count=summary.positive,
            negative_count=summary.negative,
            satisfaction_rate=self._percentage(summary.positive, summary.total),
        )

    async def ai_runs(
        self,
        principal: Principal,
        period: AnalyticsPeriodQuery,
    ) -> AIRunMetricsResponse:
        start_at, end_at = self._bounds(period)
        try:
            summary = await self._repository.get_ai_run_summary(
                tenant_id=principal.tenant_id,
                start_at=start_at,
                end_at=end_at,
            )
        except AnalyticsRepositoryError as exc:
            raise self._unavailable_error() from exc
        terminal = self._terminal_count(summary)
        return AIRunMetricsResponse(
            period=self._period_response(period),
            total=summary.total,
            running=summary.running,
            succeeded=summary.succeeded,
            failed=summary.failed,
            cancelled=summary.cancelled,
            terminal=terminal,
            success_rate=self._percentage(summary.succeeded, terminal),
            average_duration_ms=self._rounded(summary.average_duration_ms),
            average_input_tokens=self._rounded(summary.average_input_tokens),
            average_output_tokens=self._rounded(summary.average_output_tokens),
            by_model=[self._model_response(item) for item in summary.by_model],
            errors=[
                AIErrorMetrics(code=item.code, count=item.count)
                for item in summary.errors
            ],
        )

    @classmethod
    def _model_response(cls, item) -> AIModelMetrics:
        terminal = item.succeeded + item.failed + item.cancelled
        return AIModelMetrics(
            provider=item.provider,
            model=item.model,
            total=item.total,
            running=item.running,
            succeeded=item.succeeded,
            failed=item.failed,
            cancelled=item.cancelled,
            terminal=terminal,
            success_rate=cls._percentage(item.succeeded, terminal),
            average_duration_ms=cls._rounded(item.average_duration_ms),
        )

    @classmethod
    def _summary_cards(
        cls,
        *,
        tickets: TicketSummary,
        ai_runs: AIRunSummary,
        feedback: SatisfactionSummary,
    ) -> list[AnalyticsSummaryCard]:
        terminal = cls._terminal_count(ai_runs)
        return [
            AnalyticsSummaryCard(
                code="consultation_volume",
                title="咨询量",
                value=str(tickets.total),
                description=f"所选时间范围内共创建 {tickets.total} 条客服咨询。",
            ),
            AnalyticsSummaryCard(
                code="human_takeover_rate",
                title="人工接管率",
                value=f"{cls._percentage(tickets.human_takeover, tickets.total):.2f}%",
                description=(
                    f"共有 {tickets.human_takeover} 条咨询进入人工处理。"
                    if tickets.total
                    else "所选时间范围内暂无咨询。"
                ),
            ),
            AnalyticsSummaryCard(
                code="ai_success_rate",
                title="AI 成功率",
                value=f"{cls._percentage(ai_runs.succeeded, terminal):.2f}%",
                description=(
                    f"{terminal} 次终态 AI Run 中有 {ai_runs.succeeded} 次成功。"
                    if terminal
                    else "所选时间范围内暂无终态 AI Run。"
                ),
            ),
            AnalyticsSummaryCard(
                code="satisfaction_rate",
                title="满意度",
                value=f"{cls._percentage(feedback.positive, feedback.total):.2f}%",
                description=(
                    f"{feedback.total} 条评价中有 {feedback.positive} 条正面评价。"
                    if feedback.total
                    else "所选时间范围内暂无评价。"
                ),
            ),
        ]

    @staticmethod
    def _bounds(period: AnalyticsPeriodQuery) -> tuple[datetime, datetime]:
        assert period.start_date is not None and period.end_date is not None
        start_at = datetime.combine(period.start_date, time.min, tzinfo=UTC)
        end_at = datetime.combine(
            period.end_date + timedelta(days=1),
            time.min,
            tzinfo=UTC,
        )
        return start_at, end_at

    @staticmethod
    def _period_response(period: AnalyticsPeriodQuery) -> AnalyticsPeriodResponse:
        assert period.start_date is not None and period.end_date is not None
        return AnalyticsPeriodResponse(
            start_date=period.start_date,
            end_date=period.end_date,
        )

    @staticmethod
    def _terminal_count(summary: AIRunSummary) -> int:
        return summary.succeeded + summary.failed + summary.cancelled

    @staticmethod
    def _percentage(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round((numerator / denominator) * 100, 2)

    @staticmethod
    def _rounded(value: float | None) -> float:
        return round(max(value or 0.0, 0.0), 2)

    @staticmethod
    def _unavailable_error() -> AppError:
        return AppError(
            code="analytics_unavailable",
            message="统计服务暂时不可用，请稍后重试。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
