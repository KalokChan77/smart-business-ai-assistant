from uuid import UUID

from fastapi import status

from app.auth.principal import Principal
from app.core.errors import AppError
from app.customer_service.models import (
    CustomerTicket,
    CustomerTicketCategory,
    CustomerTicketPriority,
    CustomerTicketStatus,
    ReplySuggestion,
    ReplySuggestionStatus,
)
from app.customer_service.ports import (
    CustomerServiceRepositoryError,
    CustomerServiceRepositoryPort,
    CustomerServiceWorkflowPort,
    CustomerTicketNotActionableError,
    CustomerTicketNotFoundError,
    ReplySuggestionAlreadyConfirmedError,
    ReplySuggestionNotFoundError,
    TicketClassifier,
)
from app.customer_service.schemas import (
    ConfirmedReplyPublicResponse,
    CustomerTicketClassificationResponse,
    CustomerTicketCreateRequest,
    CustomerTicketDetailResponse,
    CustomerTicketInternalDetailResponse,
    CustomerTicketInternalResponse,
    CustomerTicketListResponse,
    CustomerTicketPublicDetailResponse,
    CustomerTicketPublicResponse,
    ReplySuggestionConfirmRequest,
    ReplySuggestionResponse,
)

_STAFF_ROLES = frozenset({"customer_service", "admin"})


class CustomerService:
    def __init__(
        self,
        *,
        repository: CustomerServiceRepositoryPort,
        classifier: TicketClassifier,
        workflow: CustomerServiceWorkflowPort,
    ) -> None:
        self._repository = repository
        self._classifier = classifier
        self._workflow = workflow

    async def create_ticket(
        self,
        principal: Principal,
        request: CustomerTicketCreateRequest,
    ) -> CustomerTicketPublicResponse:
        ticket = CustomerTicket(
            tenant_id=principal.tenant_id,
            requester_user_id=principal.user_id,
            subject=request.subject,
            description=request.description,
            status=CustomerTicketStatus.OPEN,
            priority=CustomerTicketPriority.NORMAL,
        )
        try:
            saved = await self._repository.create_ticket(ticket)
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        return CustomerTicketPublicResponse.from_entity(saved)

    async def list_tickets(
        self,
        principal: Principal,
        *,
        status_filter: CustomerTicketStatus | None,
        category_filter: CustomerTicketCategory | None,
        limit: int,
        offset: int,
    ) -> CustomerTicketListResponse:
        staff = self._is_staff(principal)
        try:
            tickets = await self._repository.list_visible_tickets(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                staff=staff,
                status=status_filter,
                category=category_filter,
                limit=limit,
                offset=offset,
            )
            total = await self._repository.count_visible_tickets(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                staff=staff,
                status=status_filter,
                category=category_filter,
            )
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        return CustomerTicketListResponse(
            items=[
                CustomerTicketPublicResponse.from_entity(ticket) for ticket in tickets
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_ticket(
        self,
        principal: Principal,
        ticket_id: UUID,
    ) -> CustomerTicketDetailResponse:
        staff = self._is_staff(principal)
        try:
            detail = await self._repository.get_visible_detail(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                staff=staff,
                ticket_id=ticket_id,
            )
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        if detail is None:
            raise self._ticket_not_found()
        ticket, suggestion = detail
        if staff:
            return CustomerTicketInternalDetailResponse(
                ticket=CustomerTicketInternalResponse.from_entity(ticket),
                reply_suggestion=(
                    ReplySuggestionResponse.from_entity(suggestion)
                    if suggestion is not None
                    else None
                ),
            )
        return CustomerTicketPublicDetailResponse(
            ticket=CustomerTicketPublicResponse.from_entity(ticket),
            confirmed_reply=(
                ConfirmedReplyPublicResponse.from_entity(suggestion)
                if suggestion is not None
                else None
            ),
        )

    async def classify_ticket(
        self,
        principal: Principal,
        ticket_id: UUID,
    ) -> CustomerTicketClassificationResponse:
        detail = await self._require_staff_ticket(principal, ticket_id)
        ticket, _ = detail
        classification = self._classifier.classify(ticket.subject, ticket.description)
        try:
            saved = await self._repository.classify_ticket(
                tenant_id=principal.tenant_id,
                actor_user_id=principal.user_id,
                ticket_id=ticket_id,
                classification=classification,
            )
        except CustomerTicketNotFoundError as exc:
            raise self._ticket_not_found() from exc
        except CustomerTicketNotActionableError as exc:
            raise self._ticket_not_actionable() from exc
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        return CustomerTicketClassificationResponse.from_entity(saved)

    async def generate_suggestion(
        self,
        principal: Principal,
        ticket_id: UUID,
    ) -> ReplySuggestionResponse:
        ticket, suggestion = await self._require_staff_ticket(principal, ticket_id)
        if suggestion is not None and suggestion.status == ReplySuggestionStatus.CONFIRMED:
            raise self._already_confirmed()
        if ticket.status in {
            CustomerTicketStatus.RESOLVED,
            CustomerTicketStatus.CLOSED,
        }:
            raise self._ticket_not_actionable()

        result = await self._workflow.run(
            principal,
            subject=ticket.subject,
            description=ticket.description,
        )
        try:
            _, suggestion = await self._repository.save_generated_suggestion(
                tenant_id=principal.tenant_id,
                actor_user_id=principal.user_id,
                ticket_id=ticket_id,
                result=result,
            )
        except CustomerTicketNotFoundError as exc:
            raise self._ticket_not_found() from exc
        except CustomerTicketNotActionableError as exc:
            raise self._ticket_not_actionable() from exc
        except ReplySuggestionAlreadyConfirmedError as exc:
            raise self._already_confirmed() from exc
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        return ReplySuggestionResponse.from_entity(suggestion)

    async def confirm_suggestion(
        self,
        principal: Principal,
        suggestion_id: UUID,
        request: ReplySuggestionConfirmRequest,
    ) -> CustomerTicketInternalDetailResponse:
        try:
            ticket, suggestion = await self._repository.confirm_suggestion(
                tenant_id=principal.tenant_id,
                actor_user_id=principal.user_id,
                suggestion_id=suggestion_id,
                final_reply=request.final_reply,
            )
        except ReplySuggestionNotFoundError as exc:
            raise self._suggestion_not_found() from exc
        except ReplySuggestionAlreadyConfirmedError as exc:
            raise self._already_confirmed() from exc
        except CustomerTicketNotActionableError as exc:
            raise self._ticket_not_actionable() from exc
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        return CustomerTicketInternalDetailResponse(
            ticket=CustomerTicketInternalResponse.from_entity(ticket),
            reply_suggestion=ReplySuggestionResponse.from_entity(suggestion),
        )

    async def _require_staff_ticket(
        self,
        principal: Principal,
        ticket_id: UUID,
    ) -> tuple[CustomerTicket, ReplySuggestion | None]:
        try:
            detail = await self._repository.get_visible_detail(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                staff=True,
                ticket_id=ticket_id,
            )
        except CustomerServiceRepositoryError as exc:
            raise self._persistence_error() from exc
        if detail is None:
            raise self._ticket_not_found()
        return detail

    @staticmethod
    def _is_staff(principal: Principal) -> bool:
        return not principal.roles.isdisjoint(_STAFF_ROLES)

    @staticmethod
    def _ticket_not_found() -> AppError:
        return AppError(
            code="customer_ticket_not_found",
            message="客服工单不存在。",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def _suggestion_not_found() -> AppError:
        return AppError(
            code="reply_suggestion_not_found",
            message="客服建议不存在。",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def _ticket_not_actionable() -> AppError:
        return AppError(
            code="customer_ticket_not_actionable",
            message="该工单已经完成，不能继续处理。",
            status_code=status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _already_confirmed() -> AppError:
        return AppError(
            code="reply_suggestion_already_confirmed",
            message="该建议已经确认，不能重新生成或修改。",
            status_code=status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _persistence_error() -> AppError:
        return AppError(
            code="customer_service_persistence_failed",
            message="客服业务状态暂时无法保存，请稍后重试。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
