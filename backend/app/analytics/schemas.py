from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnalyticsCategory = Literal[
    "refund_after_sales",
    "account_security",
    "product_service",
    "knowledge_document",
    "technical_support",
    "other",
    "unclassified",
]

_DEFAULT_PERIOD_DAYS = 30
_MAX_PERIOD_DAYS = 366


class AnalyticsPeriodQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def resolve_and_validate_period(self) -> "AnalyticsPeriodQuery":
        today = datetime.now(UTC).date()
        resolved_end = self.end_date or today
        resolved_start = self.start_date or (
            resolved_end - timedelta(days=_DEFAULT_PERIOD_DAYS - 1)
        )
        if resolved_start > resolved_end:
            raise ValueError("start_date must not be later than end_date")
        if (resolved_end - resolved_start).days + 1 > _MAX_PERIOD_DAYS:
            raise ValueError("analytics period must not exceed 366 days")
        self.start_date = resolved_start
        self.end_date = resolved_end
        return self


class AnalyticsPeriodResponse(BaseModel):
    start_date: date
    end_date: date
    timezone: Literal["UTC"] = "UTC"


class TopQuestionResponse(BaseModel):
    question: str = Field(min_length=1, max_length=120)
    count: int = Field(ge=2)


class AnalyticsSummaryCard(BaseModel):
    code: str
    title: str
    value: str
    description: str


class AnalyticsOverviewResponse(BaseModel):
    period: AnalyticsPeriodResponse
    consultation_count: int = Field(ge=0)
    resolved_consultation_count: int = Field(ge=0)
    resolution_rate: float = Field(ge=0, le=100)
    human_takeover_count: int = Field(ge=0)
    human_takeover_rate: float = Field(ge=0, le=100)
    ai_run_count: int = Field(ge=0)
    ai_terminal_run_count: int = Field(ge=0)
    ai_success_rate: float = Field(ge=0, le=100)
    feedback_count: int = Field(ge=0)
    positive_feedback_count: int = Field(ge=0)
    satisfaction_rate: float = Field(ge=0, le=100)
    top_questions: list[TopQuestionResponse]
    summary_cards: list[AnalyticsSummaryCard]


class ConsultationTrendPoint(BaseModel):
    date: date
    consultation_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    human_takeover_count: int = Field(ge=0)


class ConsultationTrendResponse(BaseModel):
    period: AnalyticsPeriodResponse
    points: list[ConsultationTrendPoint]


class CategoryDistributionItem(BaseModel):
    category: AnalyticsCategory
    count: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)


class CategoryDistributionResponse(BaseModel):
    period: AnalyticsPeriodResponse
    total: int = Field(ge=0)
    items: list[CategoryDistributionItem]


class SatisfactionResponse(BaseModel):
    period: AnalyticsPeriodResponse
    feedback_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    satisfaction_rate: float = Field(ge=0, le=100)


class AIModelMetrics(BaseModel):
    provider: str
    model: str
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    running: int = Field(ge=0)
    terminal: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=100)
    average_duration_ms: float = Field(ge=0)


class AIErrorMetrics(BaseModel):
    code: str
    count: int = Field(ge=1)


class AIRunMetricsResponse(BaseModel):
    period: AnalyticsPeriodResponse
    total: int = Field(ge=0)
    running: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    terminal: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=100)
    average_duration_ms: float = Field(ge=0)
    average_input_tokens: float = Field(ge=0)
    average_output_tokens: float = Field(ge=0)
    by_model: list[AIModelMetrics]
    errors: list[AIErrorMetrics]
