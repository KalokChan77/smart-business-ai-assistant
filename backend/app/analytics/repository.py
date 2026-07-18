from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIRun, AIRunStatus
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
from app.customer_service.models import CustomerTicket, CustomerTicketStatus
from app.feedback.models import AIFeedback, FeedbackRating

_RESOLVED_TICKET_STATUSES = (
    CustomerTicketStatus.RESOLVED,
    CustomerTicketStatus.CLOSED,
)
_TERMINAL_RUN_STATUSES = (
    AIRunStatus.SUCCEEDED,
    AIRunStatus.FAILED,
    AIRunStatus.CANCELLED,
)


class SQLAlchemyAnalyticsRepository:
    """Run tenant-scoped, read-only aggregates against PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_ticket_summary(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> TicketSummary:
        statement = select(
            func.count(CustomerTicket.id),
            func.count(CustomerTicket.id).filter(
                CustomerTicket.status.in_(_RESOLVED_TICKET_STATUSES)
            ),
            func.count(CustomerTicket.id).filter(
                CustomerTicket.assigned_user_id.is_not(None)
            ),
        ).where(
            CustomerTicket.tenant_id == tenant_id,
            CustomerTicket.created_at >= start_at,
            CustomerTicket.created_at < end_at,
        )
        try:
            total, resolved, human_takeover = (
                await self._session.execute(statement)
            ).one()
            return TicketSummary(
                total=int(total or 0),
                resolved=int(resolved or 0),
                human_takeover=int(human_takeover or 0),
            )
        except SQLAlchemyError as exc:
            raise AnalyticsRepositoryError from exc

    async def get_daily_consultations(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[DailyConsultationSummary, ...]:
        day_bucket = cast(
            func.timezone("UTC", CustomerTicket.created_at),
            Date,
        ).label("day")
        statement = (
            select(
                day_bucket,
                func.count(CustomerTicket.id),
                func.count(CustomerTicket.id).filter(
                    CustomerTicket.status.in_(_RESOLVED_TICKET_STATUSES)
                ),
                func.count(CustomerTicket.id).filter(
                    CustomerTicket.assigned_user_id.is_not(None)
                ),
            )
            .where(
                CustomerTicket.tenant_id == tenant_id,
                CustomerTicket.created_at >= start_at,
                CustomerTicket.created_at < end_at,
            )
            .group_by(day_bucket)
            .order_by(day_bucket)
        )
        try:
            rows = (await self._session.execute(statement)).all()
            return tuple(
                DailyConsultationSummary(
                    day=self._as_date(day),
                    total=int(total or 0),
                    resolved=int(resolved or 0),
                    human_takeover=int(human_takeover or 0),
                )
                for day, total, resolved, human_takeover in rows
            )
        except SQLAlchemyError as exc:
            raise AnalyticsRepositoryError from exc

    async def get_category_distribution(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[CategorySummary, ...]:
        statement = (
            select(CustomerTicket.category, func.count(CustomerTicket.id))
            .where(
                CustomerTicket.tenant_id == tenant_id,
                CustomerTicket.created_at >= start_at,
                CustomerTicket.created_at < end_at,
            )
            .group_by(CustomerTicket.category)
        )
        try:
            rows = (await self._session.execute(statement)).all()
            return tuple(
                CategorySummary(category=category, count=int(count or 0))
                for category, count in rows
            )
        except SQLAlchemyError as exc:
            raise AnalyticsRepositoryError from exc

    async def get_satisfaction_summary(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> SatisfactionSummary:
        statement = (
            select(
                func.count(AIFeedback.id),
                func.count(AIFeedback.id).filter(
                    AIFeedback.rating == FeedbackRating.POSITIVE
                ),
                func.count(AIFeedback.id).filter(
                    AIFeedback.rating == FeedbackRating.NEGATIVE
                ),
            )
            .select_from(AIFeedback)
            .join(AIRun, AIRun.id == AIFeedback.run_id)
            .where(
                AIRun.tenant_id == tenant_id,
                AIFeedback.created_at >= start_at,
                AIFeedback.created_at < end_at,
            )
        )
        try:
            total, positive, negative = (
                await self._session.execute(statement)
            ).one()
            return SatisfactionSummary(
                total=int(total or 0),
                positive=int(positive or 0),
                negative=int(negative or 0),
            )
        except SQLAlchemyError as exc:
            raise AnalyticsRepositoryError from exc

    async def get_top_questions(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[TopQuestionSummary, ...]:
        count_expression = func.count(CustomerTicket.id)
        statement = (
            select(CustomerTicket.subject, count_expression.label("question_count"))
            .where(
                CustomerTicket.tenant_id == tenant_id,
                CustomerTicket.created_at >= start_at,
                CustomerTicket.created_at < end_at,
            )
            .group_by(CustomerTicket.subject)
            .having(count_expression >= 2)
            .order_by(count_expression.desc(), CustomerTicket.subject.asc())
            .limit(limit)
        )
        try:
            rows = (await self._session.execute(statement)).all()
            return tuple(
                TopQuestionSummary(question=subject, count=int(count))
                for subject, count in rows
            )
        except SQLAlchemyError as exc:
            raise AnalyticsRepositoryError from exc

    async def get_ai_run_summary(
        self,
        *,
        tenant_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> AIRunSummary:
        duration_ms = (
            func.extract("epoch", AIRun.completed_at - AIRun.started_at) * 1000
        )
        base_conditions = (
            AIRun.tenant_id == tenant_id,
            AIRun.created_at >= start_at,
            AIRun.created_at < end_at,
        )
        overall_statement = select(
            func.count(AIRun.id),
            func.count(AIRun.id).filter(AIRun.status == AIRunStatus.RUNNING),
            func.count(AIRun.id).filter(AIRun.status == AIRunStatus.SUCCEEDED),
            func.count(AIRun.id).filter(AIRun.status == AIRunStatus.FAILED),
            func.count(AIRun.id).filter(AIRun.status == AIRunStatus.CANCELLED),
            func.avg(duration_ms).filter(
                AIRun.status.in_(_TERMINAL_RUN_STATUSES),
                AIRun.completed_at.is_not(None),
                AIRun.completed_at >= AIRun.started_at,
            ),
            func.avg(AIRun.input_tokens).filter(AIRun.input_tokens.is_not(None)),
            func.avg(AIRun.output_tokens).filter(AIRun.output_tokens.is_not(None)),
        ).where(*base_conditions)
        by_model_statement = (
            select(
                AIRun.provider,
                AIRun.model,
                func.count(AIRun.id),
                func.count(AIRun.id).filter(AIRun.status == AIRunStatus.RUNNING),
                func.count(AIRun.id).filter(AIRun.status == AIRunStatus.SUCCEEDED),
                func.count(AIRun.id).filter(AIRun.status == AIRunStatus.FAILED),
                func.count(AIRun.id).filter(AIRun.status == AIRunStatus.CANCELLED),
                func.avg(duration_ms).filter(
                    AIRun.status.in_(_TERMINAL_RUN_STATUSES),
                    AIRun.completed_at.is_not(None),
                    AIRun.completed_at >= AIRun.started_at,
                ),
            )
            .where(*base_conditions)
            .group_by(AIRun.provider, AIRun.model)
            .order_by(func.count(AIRun.id).desc(), AIRun.provider, AIRun.model)
        )
        error_code = func.coalesce(AIRun.error_code, "unknown")
        error_count = func.count(AIRun.id)
        error_statement = (
            select(error_code.label("error_code"), error_count.label("error_count"))
            .where(
                *base_conditions,
                AIRun.status == AIRunStatus.FAILED,
            )
            .group_by(error_code)
            .order_by(error_count.desc(), error_code.asc())
            .limit(10)
        )
        try:
            (
                total,
                running,
                succeeded,
                failed,
                cancelled,
                average_duration_ms,
                average_input_tokens,
                average_output_tokens,
            ) = (await self._session.execute(overall_statement)).one()
            model_rows = (await self._session.execute(by_model_statement)).all()
            error_rows = (await self._session.execute(error_statement)).all()
            return AIRunSummary(
                total=int(total or 0),
                running=int(running or 0),
                succeeded=int(succeeded or 0),
                failed=int(failed or 0),
                cancelled=int(cancelled or 0),
                average_duration_ms=self._as_optional_float(average_duration_ms),
                average_input_tokens=self._as_optional_float(average_input_tokens),
                average_output_tokens=self._as_optional_float(average_output_tokens),
                by_model=tuple(
                    AIModelSummary(
                        provider=provider,
                        model=model,
                        total=int(model_total or 0),
                        running=int(model_running or 0),
                        succeeded=int(model_succeeded or 0),
                        failed=int(model_failed or 0),
                        cancelled=int(model_cancelled or 0),
                        average_duration_ms=self._as_optional_float(model_duration),
                    )
                    for (
                        provider,
                        model,
                        model_total,
                        model_running,
                        model_succeeded,
                        model_failed,
                        model_cancelled,
                        model_duration,
                    ) in model_rows
                ),
                errors=tuple(
                    AIErrorSummary(code=code, count=int(count))
                    for code, count in error_rows
                ),
            )
        except SQLAlchemyError as exc:
            raise AnalyticsRepositoryError from exc

    @staticmethod
    def _as_optional_float(value: object | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _as_date(value: date | datetime) -> date:
        return value.date() if isinstance(value, datetime) else value
