from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.auth.dependencies import get_current_principal, require_any_role
from app.auth.principal import Principal
from app.customer_service.dependencies import get_customer_service
from app.customer_service.models import CustomerTicketCategory, CustomerTicketStatus
from app.customer_service.schemas import (
    CustomerTicketActionRequest,
    CustomerTicketClassificationResponse,
    CustomerTicketCreateRequest,
    CustomerTicketDetailResponse,
    CustomerTicketInternalDetailResponse,
    CustomerTicketListResponse,
    CustomerTicketPublicResponse,
    ReplySuggestionConfirmRequest,
    ReplySuggestionResponse,
)
from app.customer_service.service import CustomerService

router = APIRouter(prefix="/customer-service", tags=["customer-service"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
StaffPrincipal = Annotated[
    Principal,
    Depends(require_any_role("customer_service", "admin")),
]
CustomerServiceDependency = Annotated[
    CustomerService,
    Depends(get_customer_service),
]


@router.post(
    "/tickets",
    response_model=CustomerTicketPublicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建当前用户的客服工单",
)
async def create_ticket(
    payload: CustomerTicketCreateRequest,
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
) -> CustomerTicketPublicResponse:
    return await service.create_ticket(principal, payload)


@router.get(
    "/tickets",
    response_model=CustomerTicketListResponse,
    summary="查询当前可见的客服工单",
)
async def list_tickets(
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
    status_filter: Annotated[
        CustomerTicketStatus | None,
        Query(alias="status"),
    ] = None,
    category_filter: Annotated[
        CustomerTicketCategory | None,
        Query(alias="category"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerTicketListResponse:
    return await service.list_tickets(
        principal,
        status_filter=status_filter,
        category_filter=category_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tickets/{ticket_id}",
    response_model=CustomerTicketDetailResponse,
    summary="查询客服工单详情",
)
async def get_ticket(
    ticket_id: UUID,
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
) -> CustomerTicketDetailResponse:
    return await service.get_ticket(principal, ticket_id)


@router.post(
    "/classify",
    response_model=CustomerTicketClassificationResponse,
    summary="分类当前租户客服工单",
)
async def classify_ticket(
    payload: CustomerTicketActionRequest,
    principal: StaffPrincipal,
    service: CustomerServiceDependency,
) -> CustomerTicketClassificationResponse:
    return await service.classify_ticket(principal, payload.ticket_id)


@router.post(
    "/reply-suggestions",
    response_model=ReplySuggestionResponse,
    summary="生成当前租户工单的知识增强建议回复",
)
async def generate_reply_suggestion(
    payload: CustomerTicketActionRequest,
    principal: StaffPrincipal,
    service: CustomerServiceDependency,
) -> ReplySuggestionResponse:
    return await service.generate_suggestion(principal, payload.ticket_id)


@router.post(
    "/reply-suggestions/{suggestion_id}/confirm",
    response_model=CustomerTicketInternalDetailResponse,
    summary="人工编辑并确认客服回复",
)
async def confirm_reply_suggestion(
    suggestion_id: UUID,
    payload: ReplySuggestionConfirmRequest,
    principal: StaffPrincipal,
    service: CustomerServiceDependency,
) -> CustomerTicketInternalDetailResponse:
    return await service.confirm_suggestion(principal, suggestion_id, payload)
