from typing import Protocol
from uuid import UUID

from app.feedback.models import AIFeedback, FeedbackRating


class FeedbackRunNotFoundError(Exception):
    """Raised when the current principal does not own the requested AI Run."""


class FeedbackRunNotFeedbackableError(Exception):
    """Raised when an AI Run has no valid completed assistant response."""


class FeedbackRepositoryError(Exception):
    """Raised when feedback state cannot be read or persisted."""


class FeedbackSubmissionPort(Protocol):
    async def submit_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        run_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> AIFeedback: ...
