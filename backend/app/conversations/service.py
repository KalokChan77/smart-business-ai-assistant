from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import status

from app.auth.principal import Principal
from app.conversations.models import Conversation, Message, MessageRole
from app.conversations.repository import ConversationsRepository
from app.conversations.schemas import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
)
from app.core.errors import AppError

DEFAULT_CONVERSATION_TITLE = "新对话"
MAX_MESSAGE_LENGTH = 100_000


class ConversationService:
    def __init__(self, repository: ConversationsRepository) -> None:
        self._repository = repository

    async def create(
        self,
        principal: Principal,
        request: ConversationCreateRequest,
    ) -> ConversationResponse:
        conversation = Conversation(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            title=request.title or DEFAULT_CONVERSATION_TITLE,
        )
        await self._repository.save_conversation(conversation)
        return ConversationResponse.from_entity(conversation)

    async def list(
        self,
        principal: Principal,
        *,
        limit: int,
        offset: int,
    ) -> ConversationListResponse:
        conversations = await self._repository.list_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            limit=limit,
            offset=offset,
        )
        total = await self._repository.count_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
        return ConversationListResponse(
            items=[ConversationResponse.from_entity(item) for item in conversations],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get(
        self,
        principal: Principal,
        conversation_id: UUID,
    ) -> ConversationResponse:
        conversation = await self._require_owned(principal, conversation_id)
        return ConversationResponse.from_entity(conversation)

    async def list_messages(
        self,
        principal: Principal,
        conversation_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> MessageListResponse:
        await self._require_owned(principal, conversation_id)
        messages = await self._repository.list_messages_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
        total = await self._repository.count_messages_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
        )
        return MessageListResponse(
            items=[MessageResponse.from_entity(item) for item in messages],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def recent_messages(
        self,
        principal: Principal,
        conversation_id: UUID,
        *,
        limit: int,
    ) -> list[MessageResponse]:
        await self._require_owned(principal, conversation_id)
        messages = await self._repository.list_recent_messages_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
            limit=limit,
        )
        return [MessageResponse.from_entity(item) for item in messages]

    async def delete(self, principal: Principal, conversation_id: UUID) -> None:
        conversation = await self._require_owned(principal, conversation_id)
        await self._repository.soft_delete(
            conversation,
            deleted_at=datetime.now(UTC),
        )

    async def append_message(
        self,
        principal: Principal,
        conversation_id: UUID,
        *,
        role: MessageRole,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> MessageResponse:
        normalized_content = content.strip()
        if not normalized_content:
            raise AppError(
                code="message_content_required",
                message="消息内容不能为空。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        if len(normalized_content) > MAX_MESSAGE_LENGTH:
            raise AppError(
                code="message_too_long",
                message="消息内容超过长度限制。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        message = Message(
            conversation_id=conversation_id,
            position=0,
            role=role,
            content=normalized_content,
            message_metadata=dict(metadata or {}),
        )
        saved = await self._repository.append_message_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
            message=message,
        )
        if saved is None:
            raise self._not_found()
        return MessageResponse.from_entity(saved)

    async def _require_owned(
        self,
        principal: Principal,
        conversation_id: UUID,
    ) -> Conversation:
        conversation = await self._repository.get_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise self._not_found()
        return conversation

    @staticmethod
    def _not_found() -> AppError:
        return AppError(
            code="conversation_not_found",
            message="会话不存在。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
