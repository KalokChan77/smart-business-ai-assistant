from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.customer_service.models import (
    CustomerTicket,
    CustomerTicketCategory,
    CustomerTicketStatus,
    ReplySuggestion,
    ReplySuggestionStatus,
)
from app.customer_service.ports import (
    CustomerServiceRepositoryError,
    CustomerServiceWorkflowResult,
    CustomerTicketNotActionableError,
    CustomerTicketNotFoundError,
    ReplySuggestionAlreadyConfirmedError,
    ReplySuggestionNotFoundError,
    TicketClassification,
)


class CustomerServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_ticket(self, ticket: CustomerTicket) -> CustomerTicket:
        try:
            self._session.add(ticket)
            await self._session.commit()
            await self._session.refresh(ticket)
            return ticket
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def list_visible_tickets(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
        status: CustomerTicketStatus | None,
        category: CustomerTicketCategory | None,
        limit: int,
        offset: int,
    ) -> list[CustomerTicket]:
        statement = (
            select(CustomerTicket)
            .where(
                *self._visible_conditions(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    staff=staff,
                ),
                *self._filter_conditions(status=status, category=category),
            )
            .order_by(CustomerTicket.created_at.desc(), CustomerTicket.id.desc())
            .limit(limit)
            .offset(offset)
        )
        try:
            return list((await self._session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def count_visible_tickets(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
        status: CustomerTicketStatus | None,
        category: CustomerTicketCategory | None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(CustomerTicket)
            .where(
                *self._visible_conditions(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    staff=staff,
                ),
                *self._filter_conditions(status=status, category=category),
            )
        )
        try:
            return int((await self._session.scalar(statement)) or 0)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def get_visible_detail(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
        ticket_id: UUID,
    ) -> tuple[CustomerTicket, ReplySuggestion | None] | None:
        statement = select(CustomerTicket).where(
            CustomerTicket.id == ticket_id,
            *self._visible_conditions(
                tenant_id=tenant_id,
                user_id=user_id,
                staff=staff,
            ),
        )
        try:
            ticket = await self._session.scalar(statement)
            if ticket is None:
                return None
            suggestion_conditions = [
                ReplySuggestion.ticket_id == ticket.id,
                ReplySuggestion.tenant_id == tenant_id,
            ]
            if not staff:
                suggestion_conditions.append(
                    ReplySuggestion.status == ReplySuggestionStatus.CONFIRMED
                )
            suggestion = await self._session.scalar(
                select(ReplySuggestion).where(*suggestion_conditions)
            )
            return ticket, suggestion
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def classify_ticket(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        ticket_id: UUID,
        classification: TicketClassification,
    ) -> CustomerTicket:
        try:
            ticket = await self._lock_ticket(
                tenant_id=tenant_id,
                ticket_id=ticket_id,
            )
            self._ensure_actionable(ticket)
            self._apply_classification(ticket, actor_user_id, classification)
            await self._session.commit()
            await self._session.refresh(ticket)
            return ticket
        except (CustomerTicketNotFoundError, CustomerTicketNotActionableError):
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def save_generated_suggestion(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        ticket_id: UUID,
        result: CustomerServiceWorkflowResult,
    ) -> tuple[CustomerTicket, ReplySuggestion]:
        try:
            ticket = await self._lock_ticket(
                tenant_id=tenant_id,
                ticket_id=ticket_id,
            )
            suggestion = await self._session.scalar(
                select(ReplySuggestion)
                .where(
                    ReplySuggestion.ticket_id == ticket.id,
                    ReplySuggestion.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if suggestion is not None and suggestion.status == ReplySuggestionStatus.CONFIRMED:
                await self._session.rollback()
                raise ReplySuggestionAlreadyConfirmedError

            self._ensure_actionable(ticket)
            self._apply_classification(ticket, actor_user_id, result.classification)

            citation_rows = [
                {
                    "rank": citation.rank,
                    "document_name": citation.document_name,
                    "excerpt": citation.excerpt,
                    "score": citation.score,
                }
                for citation in result.knowledge.citations
            ]
            if suggestion is None:
                suggestion = ReplySuggestion(
                    ticket_id=ticket.id,
                    tenant_id=tenant_id,
                    category=result.classification.category,
                    status=ReplySuggestionStatus.DRAFT,
                    suggested_reply=result.suggested_reply,
                    knowledge_outcome=result.knowledge.outcome,
                    citations=citation_rows,
                    quality_status=result.quality_status,
                    quality_notes=list(result.quality_notes),
                    workflow_version=result.workflow_version,
                    generated_by_user_id=actor_user_id,
                )
                self._session.add(suggestion)
            else:
                suggestion.category = result.classification.category
                suggestion.suggested_reply = result.suggested_reply
                suggestion.knowledge_outcome = result.knowledge.outcome
                suggestion.citations = citation_rows
                suggestion.quality_status = result.quality_status
                suggestion.quality_notes = list(result.quality_notes)
                suggestion.workflow_version = result.workflow_version
                suggestion.generated_by_user_id = actor_user_id

            await self._session.commit()
            await self._session.refresh(ticket)
            await self._session.refresh(suggestion)
            return ticket, suggestion
        except (
            CustomerTicketNotFoundError,
            CustomerTicketNotActionableError,
            ReplySuggestionAlreadyConfirmedError,
        ):
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def confirm_suggestion(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        suggestion_id: UUID,
        final_reply: str | None,
    ) -> tuple[CustomerTicket, ReplySuggestion]:
        try:
            ticket_id = await self._session.scalar(
                select(ReplySuggestion.ticket_id).where(
                    ReplySuggestion.id == suggestion_id,
                    ReplySuggestion.tenant_id == tenant_id,
                )
            )
            if ticket_id is None:
                await self._session.rollback()
                raise ReplySuggestionNotFoundError

            try:
                ticket = await self._lock_ticket(
                    tenant_id=tenant_id,
                    ticket_id=ticket_id,
                )
            except CustomerTicketNotFoundError as exc:
                await self._session.rollback()
                raise ReplySuggestionNotFoundError from exc

            suggestion = await self._session.scalar(
                select(ReplySuggestion)
                .where(
                    ReplySuggestion.id == suggestion_id,
                    ReplySuggestion.ticket_id == ticket.id,
                    ReplySuggestion.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if suggestion is None:
                await self._session.rollback()
                raise ReplySuggestionNotFoundError

            if suggestion.status == ReplySuggestionStatus.CONFIRMED:
                if final_reply is None or final_reply == suggestion.final_reply:
                    await self._session.commit()
                    return ticket, suggestion
                await self._session.rollback()
                raise ReplySuggestionAlreadyConfirmedError

            if ticket.status in {
                CustomerTicketStatus.RESOLVED,
                CustomerTicketStatus.CLOSED,
            }:
                await self._session.rollback()
                raise CustomerTicketNotActionableError

            suggestion.final_reply = final_reply or suggestion.suggested_reply
            suggestion.status = ReplySuggestionStatus.CONFIRMED
            suggestion.confirmed_by_user_id = actor_user_id
            suggestion.confirmed_at = datetime.now(UTC)
            ticket.status = CustomerTicketStatus.RESOLVED
            ticket.assigned_user_id = actor_user_id
            ticket.resolved_at = suggestion.confirmed_at

            await self._session.commit()
            await self._session.refresh(ticket)
            await self._session.refresh(suggestion)
            return ticket, suggestion
        except (
            ReplySuggestionNotFoundError,
            ReplySuggestionAlreadyConfirmedError,
            CustomerTicketNotActionableError,
        ):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CustomerServiceRepositoryError from exc

    async def _lock_ticket(
        self,
        *,
        tenant_id: UUID,
        ticket_id: UUID,
    ) -> CustomerTicket:
        ticket = await self._session.scalar(
            select(CustomerTicket)
            .where(
                CustomerTicket.id == ticket_id,
                CustomerTicket.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if ticket is None:
            raise CustomerTicketNotFoundError
        return ticket

    @staticmethod
    def _ensure_actionable(ticket: CustomerTicket) -> None:
        if ticket.status in {
            CustomerTicketStatus.RESOLVED,
            CustomerTicketStatus.CLOSED,
        }:
            raise CustomerTicketNotActionableError

    @staticmethod
    def _apply_classification(
        ticket: CustomerTicket,
        actor_user_id: UUID,
        classification: TicketClassification,
    ) -> None:
        ticket.category = classification.category
        ticket.priority = classification.priority
        ticket.classification_confidence = classification.confidence
        ticket.classification_reason = classification.reason
        ticket.assigned_user_id = actor_user_id
        ticket.status = CustomerTicketStatus.IN_PROGRESS

    @staticmethod
    def _visible_conditions(
        *,
        tenant_id: UUID,
        user_id: UUID,
        staff: bool,
    ) -> tuple:
        conditions: list = [CustomerTicket.tenant_id == tenant_id]
        if not staff:
            conditions.append(CustomerTicket.requester_user_id == user_id)
        return tuple(conditions)

    @staticmethod
    def _filter_conditions(
        *,
        status: CustomerTicketStatus | None,
        category: CustomerTicketCategory | None,
    ) -> tuple:
        conditions: list = []
        if status is not None:
            conditions.append(CustomerTicket.status == status)
        if category is not None:
            conditions.append(CustomerTicket.category == category)
        return tuple(conditions)
