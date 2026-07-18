from uuid import UUID

from fastapi import status

from app.auth.principal import Principal
from app.core.errors import AppError
from app.feedback.ports import (
    FeedbackRepositoryError,
    FeedbackRunNotFeedbackableError,
    FeedbackRunNotFoundError,
    FeedbackSubmissionPort,
)
from app.feedback.schemas import AIFeedbackRequest, AIFeedbackResponse


class FeedbackService:
    def __init__(self, repository: FeedbackSubmissionPort) -> None:
        self._repository = repository

    async def submit(
        self,
        principal: Principal,
        run_id: UUID,
        request: AIFeedbackRequest,
    ) -> AIFeedbackResponse:
        try:
            feedback = await self._repository.submit_owned(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                run_id=run_id,
                rating=request.rating,
                comment=request.comment,
            )
        except FeedbackRunNotFoundError as exc:
            raise AppError(
                code="ai_run_not_found",
                message="AI 运行记录不存在。",
                status_code=status.HTTP_404_NOT_FOUND,
            ) from exc
        except FeedbackRunNotFeedbackableError as exc:
            raise AppError(
                code="ai_run_not_feedbackable",
                message="AI 运行尚未形成可评价的完整回答。",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        except FeedbackRepositoryError as exc:
            raise AppError(
                code="ai_feedback_persistence_failed",
                message="AI 回答反馈暂时无法保存，请稍后重试。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        return AIFeedbackResponse.from_entity(feedback)
