from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class FeedbackRating(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class AIFeedback(TimestampMixin, Base):
    __tablename__ = "ai_feedback"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_ai_feedback_run_id"),
        CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 1000",
            name="ai_feedback_comment_length",
        ),
        ForeignKeyConstraint(
            ["run_id", "message_id"],
            ["ai_runs.id", "ai_runs.response_message_id"],
            name="fk_ai_feedback_run_response_message_ai_runs",
            ondelete="CASCADE",
        ),
        Index(
            "ix_ai_feedback_created_rating",
            "created_at",
            "rating",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(nullable=False)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(
            FeedbackRating,
            name="ai_feedback_rating",
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text)
