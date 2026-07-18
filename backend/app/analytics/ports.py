from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.customer_service.models import CustomerTicketCategory


class AnalyticsRepositoryError(Exception):
    """Analytics data could not be aggregated from the business database."""


@dataclass(frozen=True, slots=True)
class TicketSummary:
    total: int
    resolved: int
    human_takeover: int


@dataclass(frozen=True, slots=True)
class DailyConsultationSummary:
    day: date
    total: int
    resolved: int
    human_takeover: int


@dataclass(frozen=True, slots=True)
class CategorySummary:
    category: CustomerTicketCategory | None
    count: int


@dataclass(frozen=True, slots=True)
class SatisfactionSummary:
    total: int
    positive: int
    negative: int


@dataclass(frozen=True, slots=True)
class TopQuestionSummary:
    question: str
    count: int


@dataclass(frozen=True, slots=True)
class AIModelSummary:
    provider: str
    model: str
    total: int
    running: int
    succeeded: int
    failed: int
    cancelled: int
    average_duration_ms: float | None


@dataclass(frozen=True, slots=True)
class AIErrorSummary:
    code: str
    count: int


@dataclass(frozen=True, slots=True)
class AIRunSummary:
    total: int
    running: int
    succeeded: int
    failed: int
    cancelled: int
    average_duration_ms: float | None
    average_input_tokens: float | None
    average_output_tokens: float | None
    by_model: tuple[AIModelSummary, ...]
    errors: tuple[AIErrorSummary, ...]


class AnalyticsRepository(Protocol):
    async def get_ticket_summary(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> TicketSummary: ...

    async def get_daily_consultations(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[DailyConsultationSummary, ...]: ...

    async def get_category_distribution(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[CategorySummary, ...]: ...

    async def get_satisfaction_summary(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> SatisfactionSummary: ...

    async def get_top_questions(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[TopQuestionSummary, ...]: ...

    async def get_ai_run_summary(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> AIRunSummary: ...
