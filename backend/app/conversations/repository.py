from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversations.models import Conversation, Message


class ConversationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        return await self._session.scalar(statement)

    async def list_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        statement = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(
                Conversation.last_message_at.desc().nullslast(),
                Conversation.updated_at.desc(),
                Conversation.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def count_owned(self, *, tenant_id: UUID, user_id: UUID) -> int:
        statement = select(func.count(Conversation.id)).where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        return int(await self._session.scalar(statement) or 0)

    async def list_messages_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        limit: int,
        offset: int,
    ) -> list[Message]:
        statement = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Message.position)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def list_recent_messages_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        limit: int,
    ) -> list[Message]:
        statement = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Message.position.desc())
            .limit(limit)
        )
        result = list(await self._session.scalars(statement))
        result.reverse()
        return result

    async def count_messages_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
    ) -> int:
        statement = (
            select(func.count(Message.id))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return int(await self._session.scalar(statement) or 0)

    async def save_conversation(self, conversation: Conversation) -> None:
        self._session.add(conversation)
        await self._commit()
        await self._session.refresh(conversation)

    async def append_message_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        message: Message,
    ) -> Message | None:
        statement = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        conversation = await self._session.scalar(statement)
        if conversation is None:
            return None

        occurred_at = datetime.now(UTC)
        message.conversation_id = conversation.id
        message.position = conversation.next_message_position
        message.created_at = occurred_at
        conversation.next_message_position += 1
        conversation.last_message_at = occurred_at
        conversation.updated_at = occurred_at
        self._session.add_all([conversation, message])
        await self._commit()
        await self._session.refresh(conversation)
        await self._session.refresh(message)
        return message

    async def soft_delete(
        self,
        conversation: Conversation,
        *,
        deleted_at: datetime,
    ) -> None:
        conversation.deleted_at = deleted_at
        conversation.updated_at = deleted_at
        self._session.add(conversation)
        await self._commit()
        await self._session.refresh(conversation)

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
