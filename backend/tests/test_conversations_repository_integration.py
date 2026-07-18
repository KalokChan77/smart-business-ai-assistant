import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.conversations.models import Conversation, Message, MessageRole
from app.conversations.repository import ConversationsRepository
from app.conversations.schemas import ConversationCreateRequest
from app.conversations.service import ConversationService
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.schemas import UserCreateRequest
from app.users.service import UserService

pytestmark = pytest.mark.integration


async def test_conversation_history_is_owner_scoped_ordered_and_soft_deleted() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not configured")

    tenant_a = uuid4()
    tenant_b = uuid4()
    suffix = uuid4().hex[:8]
    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username=f"conversation-admin-a-{suffix}",
                email=f"conversation-admin-a-{suffix}@example.test",
                password="integration-password",
            )

        principal_a = Principal(
            user_id=admin_a.id,
            tenant_id=tenant_a,
            username=admin_a.username,
            email=admin_a.email,
            roles=frozenset({"admin"}),
        )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            member_a = await users.create_user(
                principal_a,
                UserCreateRequest(
                    username=f"conversation-member-a-{suffix}",
                    email=f"conversation-member-a-{suffix}@example.test",
                    password="integration-password",
                    role_codes={"user"},
                ),
            )

        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"conversation-admin-b-{suffix}",
                email=f"conversation-admin-b-{suffix}@example.test",
                password="integration-password",
            )

        principal_member_a = Principal(
            user_id=member_a.id,
            tenant_id=tenant_a,
            username=member_a.username,
            email=member_a.email,
            roles=frozenset({"user"}),
        )
        principal_b = Principal(
            user_id=admin_b.id,
            tenant_id=tenant_b,
            username=admin_b.username,
            email=admin_b.email,
            roles=frozenset({"admin"}),
        )

        async with database.session_factory() as session:
            service = ConversationService(ConversationsRepository(session))
            conversation = await service.create(
                principal_a,
                ConversationCreateRequest(title="集成测试会话"),
            )
            first = await service.append_message(
                principal_a,
                conversation.id,
                role=MessageRole.USER,
                content="第一个问题",
            )
            second = await service.append_message(
                principal_a,
                conversation.id,
                role=MessageRole.ASSISTANT,
                content="第一个回答",
                metadata={"provider": "mock"},
            )
            history = await service.list_messages(
                principal_a,
                conversation.id,
                limit=100,
                offset=0,
            )
            assert [item.position for item in history.items] == [1, 2]
            assert [item.role for item in history.items] == [
                MessageRole.USER,
                MessageRole.ASSISTANT,
            ]
            assert [item.id for item in history.items] == [first.id, second.id]

            for foreign_principal in (principal_member_a, principal_b):
                with pytest.raises(AppError) as foreign:
                    await service.list_messages(
                        foreign_principal,
                        conversation.id,
                        limit=100,
                        offset=0,
                    )
                assert foreign.value.code == "conversation_not_found"

        async with database.session_factory() as session:
            repository = ConversationsRepository(session)
            assert (
                await repository.list_messages_owned(
                    tenant_id=principal_member_a.tenant_id,
                    user_id=principal_member_a.user_id,
                    conversation_id=conversation.id,
                    limit=100,
                    offset=0,
                )
                == []
            )
            assert (
                await repository.count_messages_owned(
                    tenant_id=principal_member_a.tenant_id,
                    user_id=principal_member_a.user_id,
                    conversation_id=conversation.id,
                )
                == 0
            )

        await _assert_message_constraints(database, conversation.id)
        await _assert_concurrent_positions(database, principal_a, conversation.id)

        async with database.session_factory() as session:
            service = ConversationService(ConversationsRepository(session))
            history = await service.list_messages(
                principal_a,
                conversation.id,
                limit=100,
                offset=0,
            )
            assert [item.position for item in history.items] == [1, 2, 3, 4]
            await service.delete(principal_a, conversation.id)
            assert (await service.list(principal_a, limit=20, offset=0)).total == 0
            with pytest.raises(AppError) as deleted:
                await service.list_messages(
                    principal_a,
                    conversation.id,
                    limit=100,
                    offset=0,
                )
            assert deleted.value.code == "conversation_not_found"

        async with database.session_factory() as session:
            repository = ConversationsRepository(session)
            assert (
                await repository.list_messages_owned(
                    tenant_id=principal_a.tenant_id,
                    user_id=principal_a.user_id,
                    conversation_id=conversation.id,
                    limit=100,
                    offset=0,
                )
                == []
            )
            stored = await session.get(Conversation, conversation.id)
            message_count = await session.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation.id
                )
            )
            assert stored is not None and stored.deleted_at is not None
            assert stored.next_message_position == 5
            assert int(message_count or 0) == 4
    finally:
        async with database.session_factory() as session:
            await session.execute(
                delete(User).where(User.tenant_id.in_([tenant_a, tenant_b]))
            )
            await session.execute(
                delete(Role).where(Role.tenant_id.in_([tenant_a, tenant_b]))
            )
            await session.commit()
        await database.close()


async def _assert_message_constraints(database: Database, conversation_id) -> None:
    invalid_rows = (
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "position": 1,
            "role": MessageRole.USER.value,
            "content": "重复位置",
            "metadata": {},
        },
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "position": 0,
            "role": MessageRole.USER.value,
            "content": "非法位置",
            "metadata": {},
        },
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "position": 3,
            "role": "invalid-role",
            "content": "非法角色",
            "metadata": {},
        },
    )
    for row in invalid_rows:
        async with database.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(insert(Message.__table__).values(**row))
                await session.commit()
            await session.rollback()


async def _assert_concurrent_positions(
    database: Database,
    principal: Principal,
    conversation_id,
) -> None:
    async def append(content: str):
        async with database.session_factory() as session:
            service = ConversationService(ConversationsRepository(session))
            return await service.append_message(
                principal,
                conversation_id,
                role=MessageRole.ASSISTANT,
                content=content,
            )

    appended = await asyncio.gather(append("并发回答 A"), append("并发回答 B"))
    assert sorted(item.position for item in appended) == [3, 4]
