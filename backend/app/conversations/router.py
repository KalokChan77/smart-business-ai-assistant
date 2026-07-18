from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.conversations.dependencies import get_conversation_service
from app.conversations.schemas import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
)
from app.conversations.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
ConversationServiceDependency = Annotated[
    ConversationService,
    Depends(get_conversation_service),
]


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建会话",
)
async def create_conversation(
    request: ConversationCreateRequest,
    principal: CurrentPrincipal,
    service: ConversationServiceDependency,
) -> ConversationResponse:
    return await service.create(principal, request)


@router.get("", response_model=ConversationListResponse, summary="查询当前用户会话")
async def list_conversations(
    principal: CurrentPrincipal,
    service: ConversationServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationListResponse:
    return await service.list(principal, limit=limit, offset=offset)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="查询会话详情",
)
async def get_conversation(
    conversation_id: UUID,
    principal: CurrentPrincipal,
    service: ConversationServiceDependency,
) -> ConversationResponse:
    return await service.get(principal, conversation_id)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="查询会话消息",
)
async def list_messages(
    conversation_id: UUID,
    principal: CurrentPrincipal,
    service: ConversationServiceDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageListResponse:
    return await service.list_messages(
        principal,
        conversation_id,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="软删除会话",
)
async def delete_conversation(
    conversation_id: UUID,
    principal: CurrentPrincipal,
    service: ConversationServiceDependency,
) -> Response:
    await service.delete(principal, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
