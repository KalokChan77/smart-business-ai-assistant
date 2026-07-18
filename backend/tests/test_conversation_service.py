from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.auth.principal import Principal
from app.conversations.models import Conversation, Message, MessageRole
from app.conversations.schemas import ConversationCreateRequest
from app.conversations.service import ConversationService
from app.core.errors import AppError


class FakeConversationsRepository:
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.messages: list[Message] = []

    async def get_owned(
        self, *, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> Conversation | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        if (
            conversation.tenant_id != tenant_id
            or conversation.user_id != user_id
            or conversation.deleted_at is not None
        ):
            return None
        return conversation

    async def list_owned(
        self, *, tenant_id: UUID, user_id: UUID, limit: int, offset: int
    ) -> list[Conversation]:
        values = [
            item
            for item in self.conversations.values()
            if item.tenant_id == tenant_id
            and item.user_id == user_id
            and item.deleted_at is None
        ]
        values.sort(key=lambda item: (item.updated_at, str(item.id)), reverse=True)
        return values[offset : offset + limit]

    async def count_owned(self, *, tenant_id: UUID, user_id: UUID) -> int:
        return len(
            await self.list_owned(
                tenant_id=tenant_id,
                user_id=user_id,
                limit=10_000,
                offset=0,
            )
        )

    async def list_messages_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        limit: int,
        offset: int,
    ) -> list[Message]:
        conversation = await self.get_owned(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            return []
        values = [
            item
            for item in self.messages
            if item.conversation_id == conversation_id
        ]
        values.sort(key=lambda item: item.position)
        return values[offset : offset + limit]

    async def count_messages_owned(
        self, *, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> int:
        return len(
            await self.list_messages_owned(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                limit=10_000,
                offset=0,
            )
        )

    async def save_conversation(self, conversation: Conversation) -> None:
        now = datetime.now(UTC)
        conversation.id = conversation.id or uuid4()
        conversation.next_message_position = conversation.next_message_position or 1
        conversation.created_at = now
        conversation.updated_at = now
        self.conversations[conversation.id] = conversation

    async def append_message_owned(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        message: Message,
    ) -> Message | None:
        conversation = await self.get_owned(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            return None

        occurred_at = datetime.now(UTC)
        message.id = message.id or uuid4()
        message.conversation_id = conversation.id
        message.position = conversation.next_message_position
        message.created_at = occurred_at
        conversation.next_message_position += 1
        conversation.last_message_at = occurred_at
        conversation.updated_at = occurred_at
        self.messages.append(message)
        return message

    async def soft_delete(
        self, conversation: Conversation, *, deleted_at: datetime
    ) -> None:
        conversation.deleted_at = deleted_at
        conversation.updated_at = deleted_at


def principal(*, tenant_id: UUID | None = None, user_id: UUID | None = None) -> Principal:
    return Principal(
        user_id=user_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        username="demo",
        email="demo@example.com",
        roles=frozenset({"user"}),
    )


async def test_conversation_lifecycle_and_message_order() -> None:
    repository = FakeConversationsRepository()
    service = ConversationService(repository)
    current = principal()

    created = await service.create(current, ConversationCreateRequest(title="  项目咨询  "))
    first = await service.append_message(
        current,
        created.id,
        role=MessageRole.USER,
        content=" 第一个问题 ",
    )
    second = await service.append_message(
        current,
        created.id,
        role=MessageRole.ASSISTANT,
        content="第二个回答",
        metadata={"provider": "mock"},
    )
    listed = await service.list(current, limit=20, offset=0)
    messages = await service.list_messages(current, created.id, limit=100, offset=0)

    assert created.title == "项目咨询"
    assert listed.total == 1
    assert listed.items[0].id == created.id
    assert [item.id for item in messages.items] == [first.id, second.id]
    assert [item.position for item in messages.items] == [1, 2]
    assert messages.items[0].content == "第一个问题"
    assert messages.items[1].metadata == {"provider": "mock"}

    await service.delete(current, created.id)
    assert (await service.list(current, limit=20, offset=0)).total == 0
    with pytest.raises(AppError) as captured:
        await service.get(current, created.id)
    assert captured.value.code == "conversation_not_found"


async def test_conversation_access_is_scoped_to_tenant_and_user() -> None:
    repository = FakeConversationsRepository()
    service = ConversationService(repository)
    owner = principal()
    created = await service.create(owner, ConversationCreateRequest())

    for other in (
        principal(tenant_id=uuid4(), user_id=owner.user_id),
        principal(tenant_id=owner.tenant_id, user_id=uuid4()),
    ):
        with pytest.raises(AppError) as captured:
            await service.get(other, created.id)
        assert captured.value.code == "conversation_not_found"
        with pytest.raises(AppError) as message_access:
            await service.list_messages(other, created.id, limit=100, offset=0)
        assert message_access.value.code == "conversation_not_found"


async def test_append_message_rejects_empty_and_oversized_content() -> None:
    repository = FakeConversationsRepository()
    service = ConversationService(repository)
    current = principal()
    created = await service.create(current, ConversationCreateRequest())

    with pytest.raises(AppError) as empty:
        await service.append_message(
            current,
            created.id,
            role=MessageRole.USER,
            content="   ",
        )
    assert empty.value.code == "message_content_required"

    with pytest.raises(AppError) as oversized:
        await service.append_message(
            current,
            created.id,
            role=MessageRole.USER,
            content="x" * 100_001,
        )
    assert oversized.value.code == "message_too_long"
