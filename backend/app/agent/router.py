from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agent.dependencies import get_agent_service
from app.agent.schemas import AgentStreamRequest
from app.agent.service import AgentService
from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.core.errors import request_id_for

router = APIRouter(prefix="/ai", tags=["agent"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
AgentServiceDependency = Annotated[AgentService, Depends(get_agent_service)]


@router.post(
    "/agent/stream",
    summary="LangGraph 工具调用 Agent SSE 流式执行",
    response_class=StreamingResponse,
)
async def stream_agent(
    payload: AgentStreamRequest,
    request: Request,
    principal: CurrentPrincipal,
    service: AgentServiceDependency,
) -> StreamingResponse:
    prepared = await service.prepare(principal, request_id_for(request), payload)
    return StreamingResponse(
        service.stream(principal, prepared),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
