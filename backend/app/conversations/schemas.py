from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.conversations.models import Conversation, Message, MessageRole


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, conversation: Conversation) -> "ConversationResponse":
        return cls(
            id=conversation.id,
            title=conversation.title,
            last_message_at=conversation.last_message_at,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    id: UUID
    position: int
    role: MessageRole
    content: str
    metadata: dict[str, object]
    created_at: datetime

    @classmethod
    def from_entity(cls, message: Message) -> "MessageResponse":
        return cls(
            id=message.id,
            position=message.position,
            role=message.role,
            content=message.content,
            metadata=message.message_metadata,
            created_at=message.created_at,
        )


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    total: int
    limit: int
    offset: int
