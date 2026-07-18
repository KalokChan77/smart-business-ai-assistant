from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.feedback.models import AIFeedback, FeedbackRating


class AIFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class AIFeedbackResponse(BaseModel):
    id: UUID
    run_id: UUID
    message_id: UUID
    rating: FeedbackRating
    comment: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, feedback: AIFeedback) -> "AIFeedbackResponse":
        return cls(
            id=feedback.id,
            run_id=feedback.run_id,
            message_id=feedback.message_id,
            rating=feedback.rating,
            comment=feedback.comment,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
        )
