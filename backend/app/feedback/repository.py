from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIRun, AIRunStatus
from app.conversations.models import Conversation, Message, MessageRole
from app.feedback.models import AIFeedback, FeedbackRating
from app.feedback.ports import (
    FeedbackRepositoryError,
    FeedbackRunNotFeedbackableError,
    FeedbackRunNotFoundError,
)


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def submit_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        run_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> AIFeedback:
        try:
            run = await self._session.scalar(
                select(AIRun)
                .where(
                    AIRun.id == run_id,
                    AIRun.tenant_id == tenant_id,
                    AIRun.user_id == user_id,
                )
                .with_for_update()
            )
            if run is None:
                await self._session.rollback()
                raise FeedbackRunNotFoundError
            if run.status != AIRunStatus.SUCCEEDED or run.response_message_id is None:
                await self._session.rollback()
                raise FeedbackRunNotFeedbackableError

            message = await self._session.scalar(
                select(Message)
                .join(
                    Conversation,
                    Conversation.id == Message.conversation_id,
                )
                .where(
                    Message.id == run.response_message_id,
                    Message.conversation_id == run.conversation_id,
                    Message.role == MessageRole.ASSISTANT,
                    Conversation.id == run.conversation_id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.user_id == user_id,
                    Conversation.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if message is None:
                await self._session.rollback()
                raise FeedbackRunNotFeedbackableError

            insert_statement = insert(AIFeedback).values(
                run_id=run.id,
                message_id=message.id,
                rating=rating,
                comment=comment,
            )
            statement = (
                insert_statement
                .on_conflict_do_update(
                    constraint="uq_ai_feedback_run_id",
                    set_={
                        "message_id": insert_statement.excluded.message_id,
                        "rating": insert_statement.excluded.rating,
                        "comment": insert_statement.excluded.comment,
                        "updated_at": func.now(),
                    },
                )
                .returning(AIFeedback)
                .execution_options(populate_existing=True)
            )
            feedback = (await self._session.execute(statement)).scalar_one()
            await self._session.commit()
            return feedback
        except (
            FeedbackRunNotFoundError,
            FeedbackRunNotFeedbackableError,
        ):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise FeedbackRepositoryError from exc

    async def get_owned_feedback(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        run_id: UUID,
    ) -> AIFeedback | None:
        statement = (
            select(AIFeedback)
            .join(AIRun, AIRun.id == AIFeedback.run_id)
            .where(
                AIFeedback.run_id == run_id,
                AIRun.tenant_id == tenant_id,
                AIRun.user_id == user_id,
            )
        )
        try:
            return await self._session.scalar(statement)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise FeedbackRepositoryError from exc
