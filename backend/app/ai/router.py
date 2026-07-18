from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.ai.dependencies import get_ai_chat_service
from app.ai.schemas import AIRunResponse, ChatStreamRequest
from app.ai.service import AIChatService
from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.core.errors import request_id_for

router = APIRouter(prefix="/ai", tags=["ai"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
AIChatServiceDependency = Annotated[AIChatService, Depends(get_ai_chat_service)]


@router.post(
    "/chat/stream",
    summary="普通模型 SSE 流式对话",
    response_class=StreamingResponse,
)
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
    principal: CurrentPrincipal,
    service: AIChatServiceDependency,
) -> StreamingResponse:
    prepared = await service.prepare(
        principal,
        request_id_for(request),
        payload,
    )
    return StreamingResponse(
        service.stream(principal, prepared),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/runs/{run_id}",
    response_model=AIRunResponse,
    summary="查询当前用户的 AI 运行状态",
)
async def get_ai_run(
    run_id: UUID,
    principal: CurrentPrincipal,
    service: AIChatServiceDependency,
) -> AIRunResponse:
    return await service.get_run(principal, run_id)
