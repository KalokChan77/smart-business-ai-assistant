from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.auth.principal import Principal
from app.core.errors import AppError
from app.feedback.models import AIFeedback, FeedbackRating
from app.feedback.ports import (
    FeedbackRepositoryError,
    FeedbackRunNotFeedbackableError,
    FeedbackRunNotFoundError,
)
from app.feedback.schemas import AIFeedbackRequest
from app.feedback.service import FeedbackService


class FakeFeedbackRepository:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.submit_calls: list[dict[str, object]] = []
        self.feedback_id = uuid4()
        self.message_id = uuid4()
        self.created_at = datetime.now(UTC)

    async def submit_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        run_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> AIFeedback:
        if self.error is not None:
            raise self.error
        values = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "run_id": run_id,
            "rating": rating,
            "comment": comment,
        }
        self.submit_calls.append(values)
        return AIFeedback(
            id=self.feedback_id,
            run_id=run_id,
            message_id=self.message_id,
            rating=rating,
            comment=comment,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )


def make_principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="feedback-user",
        email="feedback-user@example.test",
        roles=frozenset({"user"}),
    )


async def test_submit_passes_owner_scope_and_normalized_payload_to_repository() -> None:
    principal = make_principal()
    run_id = uuid4()
    repository = FakeFeedbackRepository()
    service = FeedbackService(repository)

    response = await service.submit(
        principal,
        run_id,
        AIFeedbackRequest(
            rating=FeedbackRating.NEGATIVE,
            comment="  缺少退款期限。  ",
        ),
    )

    assert response.id == repository.feedback_id
    assert response.run_id == run_id
    assert response.message_id == repository.message_id
    assert response.rating == FeedbackRating.NEGATIVE
    assert response.comment == "缺少退款期限。"
    assert repository.submit_calls == [
        {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "run_id": run_id,
            "rating": FeedbackRating.NEGATIVE,
            "comment": "缺少退款期限。",
        }
    ]


@pytest.mark.parametrize(
    ("repository_error", "status_code", "error_code"),
    [
        (FeedbackRunNotFoundError(), 404, "ai_run_not_found"),
        (
            FeedbackRunNotFeedbackableError(),
            409,
            "ai_run_not_feedbackable",
        ),
        (
            FeedbackRepositoryError(),
            503,
            "ai_feedback_persistence_failed",
        ),
    ],
)
async def test_submit_maps_repository_outcomes_to_stable_errors(
    repository_error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    principal = make_principal()
    repository = FakeFeedbackRepository()
    repository.error = repository_error
    service = FeedbackService(repository)

    with pytest.raises(AppError) as captured:
        await service.submit(
            principal,
            uuid4(),
            AIFeedbackRequest(rating=FeedbackRating.POSITIVE),
        )

    assert captured.value.status_code == status_code
    assert captured.value.code == error_code
    assert repository.submit_calls == []
