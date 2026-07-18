from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.feedback.dependencies import get_feedback_service
from app.feedback.schemas import AIFeedbackRequest, AIFeedbackResponse
from app.feedback.service import FeedbackService

router = APIRouter(prefix="/ai", tags=["feedback"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
FeedbackServiceDependency = Annotated[
    FeedbackService,
    Depends(get_feedback_service),
]


@router.post(
    "/runs/{run_id}/feedback",
    response_model=AIFeedbackResponse,
    summary="提交或更新当前用户的 AI 回答反馈",
)
async def submit_ai_feedback(
    run_id: UUID,
    payload: AIFeedbackRequest,
    principal: CurrentPrincipal,
    service: FeedbackServiceDependency,
) -> AIFeedbackResponse:
    return await service.submit(principal, run_id, payload)
