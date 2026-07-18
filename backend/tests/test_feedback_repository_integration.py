import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.ai.models import AIRun, AIRunStatus
from app.ai.repository import AIRunsRepository
from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.conversations.models import MessageRole
from app.conversations.repository import ConversationsRepository
from app.conversations.schemas import ConversationCreateRequest
from app.conversations.service import ConversationService
from app.core.config import Settings
from app.db.session import Database
from app.feedback.models import AIFeedback, FeedbackRating
from app.feedback.ports import (
    FeedbackRunNotFeedbackableError,
    FeedbackRunNotFoundError,
)
from app.feedback.repository import FeedbackRepository
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.schemas import UserCreateRequest
from app.users.service import UserService

pytestmark = pytest.mark.integration


async def create_messages(
    database: Database,
    principal: Principal,
    *,
    title: str,
) -> tuple[UUID, UUID, UUID]:
    async with database.session_factory() as session:
        conversations = ConversationService(ConversationsRepository(session))
        conversation = await conversations.create(
            principal,
            ConversationCreateRequest(title=title),
        )
        prompt = await conversations.append_message(
            principal,
            conversation.id,
            role=MessageRole.USER,
            content="测试问题",
        )
        response = await conversations.append_message(
            principal,
            conversation.id,
            role=MessageRole.ASSISTANT,
            content="测试回答",
        )
        return conversation.id, prompt.id, response.id


async def create_run(
    database: Database,
    principal: Principal,
    *,
    conversation_id: UUID,
    prompt_message_id: UUID | None,
    response_message_id: UUID | None,
    request_id: str,
    status: AIRunStatus = AIRunStatus.SUCCEEDED,
) -> AIRun:
    async with database.session_factory() as session:
        run = AIRun(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            provider="deepseek",
            model="deepseek-chat",
            status=status,
            prompt_message_id=prompt_message_id,
            response_message_id=response_message_id,
            completed_at=(
                datetime.now(UTC) if status == AIRunStatus.SUCCEEDED else None
            ),
        )
        await AIRunsRepository(session).create(run)
        return run


async def create_successful_run(
    database: Database,
    principal: Principal,
    *,
    request_id: str,
) -> AIRun:
    conversation_id, prompt_id, response_id = await create_messages(
        database,
        principal,
        title="反馈集成测试",
    )
    return await create_run(
        database,
        principal,
        conversation_id=conversation_id,
        prompt_message_id=prompt_id,
        response_message_id=response_id,
        request_id=request_id,
    )


async def concurrent_submit(
    database: Database,
    *,
    tenant_id: UUID,
    user_id: UUID,
    run_id: UUID,
    rating: FeedbackRating,
) -> AIFeedback:
    async with database.session_factory() as session:
        return await FeedbackRepository(session).submit_owned(
            tenant_id=tenant_id,
            user_id=user_id,
            run_id=run_id,
            rating=rating,
            comment=f"concurrent-{rating.value}",
        )


async def test_feedback_is_owner_scoped_atomic_upserted_and_constrained() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not configured")

    tenant_a = uuid4()
    tenant_b = uuid4()
    tenant_ids = (tenant_a, tenant_b)
    suffix = uuid4().hex[:8]
    tracked_run_ids: set[UUID] = set()
    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username=f"feedback-admin-a-{suffix}",
                email=f"feedback-admin-a-{suffix}@example.test",
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
            same_tenant_user = await users.create_user(
                principal_a,
                UserCreateRequest(
                    username=f"feedback-user-a-{suffix}",
                    email=f"feedback-user-a-{suffix}@example.test",
                    password="integration-password",
                    role_codes={"user"},
                ),
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"feedback-admin-b-{suffix}",
                email=f"feedback-admin-b-{suffix}@example.test",
                password="integration-password",
            )

        principal_same_tenant = Principal(
            user_id=same_tenant_user.id,
            tenant_id=tenant_a,
            username=same_tenant_user.username,
            email=same_tenant_user.email,
            roles=frozenset({"user"}),
        )
        principal_b = Principal(
            user_id=admin_b.id,
            tenant_id=tenant_b,
            username=admin_b.username,
            email=admin_b.email,
            roles=frozenset({"admin"}),
        )

        run = await create_successful_run(
            database,
            principal_a,
            request_id=f"feedback-run-{suffix}",
        )
        tracked_run_ids.add(run.id)
        response_message_id = run.response_message_id
        assert response_message_id is not None

        async with database.session_factory() as session:
            repository = FeedbackRepository(session)
            first = await repository.submit_owned(
                tenant_id=principal_a.tenant_id,
                user_id=principal_a.user_id,
                run_id=run.id,
                rating=FeedbackRating.NEGATIVE,
                comment="第一次反馈",
            )
            second = await repository.submit_owned(
                tenant_id=principal_a.tenant_id,
                user_id=principal_a.user_id,
                run_id=run.id,
                rating=FeedbackRating.POSITIVE,
                comment=None,
            )

            assert second.id == first.id
            assert second.created_at == first.created_at
            assert second.updated_at >= first.updated_at
            assert second.rating == FeedbackRating.POSITIVE
            assert second.comment is None
            assert second.message_id == response_message_id
            owned = await repository.get_owned_feedback(
                tenant_id=principal_a.tenant_id,
                user_id=principal_a.user_id,
                run_id=run.id,
            )
            assert owned is not None
            assert owned.id == first.id

        async with database.session_factory() as session:
            conversations = ConversationService(ConversationsRepository(session))
            replacement_response = await conversations.append_message(
                principal_a,
                run.conversation_id,
                role=MessageRole.ASSISTANT,
                content="替换回答不应覆盖已有反馈关联",
            )
        async with database.session_factory() as session:
            persisted_run = await session.get(AIRun, run.id)
            assert persisted_run is not None
            persisted_run.response_message_id = replacement_response.id
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        for other_principal in (principal_same_tenant, principal_b):
            async with database.session_factory() as session:
                with pytest.raises(FeedbackRunNotFoundError):
                    await FeedbackRepository(session).submit_owned(
                        tenant_id=other_principal.tenant_id,
                        user_id=other_principal.user_id,
                        run_id=run.id,
                        rating=FeedbackRating.NEGATIVE,
                        comment=None,
                    )

        concurrent_run = await create_successful_run(
            database,
            principal_a,
            request_id=f"feedback-concurrent-{suffix}",
        )
        tracked_run_ids.add(concurrent_run.id)
        results = await asyncio.gather(
            concurrent_submit(
                database,
                tenant_id=principal_a.tenant_id,
                user_id=principal_a.user_id,
                run_id=concurrent_run.id,
                rating=FeedbackRating.POSITIVE,
            ),
            concurrent_submit(
                database,
                tenant_id=principal_a.tenant_id,
                user_id=principal_a.user_id,
                run_id=concurrent_run.id,
                rating=FeedbackRating.NEGATIVE,
            ),
        )
        assert results[0].id == results[1].id
        async with database.session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.run_id == concurrent_run.id)
            )
            assert count == 1

        first_conversation, first_prompt, _ = await create_messages(
            database,
            principal_a,
            title="反馈一致性测试一",
        )
        _, _, other_response = await create_messages(
            database,
            principal_a,
            title="反馈一致性测试二",
        )
        cross_conversation_run = await create_run(
            database,
            principal_a,
            conversation_id=first_conversation,
            prompt_message_id=first_prompt,
            response_message_id=other_response,
            request_id=f"feedback-cross-message-{suffix}",
        )
        tracked_run_ids.add(cross_conversation_run.id)
        non_assistant_run = await create_run(
            database,
            principal_a,
            conversation_id=first_conversation,
            prompt_message_id=first_prompt,
            response_message_id=first_prompt,
            request_id=f"feedback-user-message-{suffix}",
        )
        tracked_run_ids.add(non_assistant_run.id)
        for invalid_run in (cross_conversation_run, non_assistant_run):
            async with database.session_factory() as session:
                with pytest.raises(FeedbackRunNotFeedbackableError):
                    await FeedbackRepository(session).submit_owned(
                        tenant_id=principal_a.tenant_id,
                        user_id=principal_a.user_id,
                        run_id=invalid_run.id,
                        rating=FeedbackRating.NEGATIVE,
                        comment=None,
                    )

        stale_run = await create_successful_run(
            database,
            principal_a,
            request_id=f"feedback-lock-{suffix}",
        )
        tracked_run_ids.add(stale_run.id)
        lock_acquired = asyncio.Event()

        async def invalidate_run() -> None:
            async with database.session_factory() as session:
                locked = await session.scalar(
                    select(AIRun)
                    .where(AIRun.id == stale_run.id)
                    .with_for_update()
                )
                assert locked is not None
                locked.status = AIRunStatus.FAILED
                lock_acquired.set()
                await asyncio.sleep(0.05)
                await session.commit()

        async def submit_after_invalidation_starts() -> None:
            await lock_acquired.wait()
            async with database.session_factory() as session:
                with pytest.raises(FeedbackRunNotFeedbackableError):
                    await FeedbackRepository(session).submit_owned(
                        tenant_id=principal_a.tenant_id,
                        user_id=principal_a.user_id,
                        run_id=stale_run.id,
                        rating=FeedbackRating.POSITIVE,
                        comment=None,
                    )

        await asyncio.gather(
            invalidate_run(),
            submit_after_invalidation_starts(),
        )
        async with database.session_factory() as session:
            stale_count = await session.scalar(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.run_id == stale_run.id)
            )
            assert stale_count == 0

        constraint_run_a = cross_conversation_run
        constraint_run_b = non_assistant_run
        invalid_rows = (
            {
                "id": uuid4(),
                "run_id": constraint_run_a.id,
                "message_id": response_message_id,
                "rating": "neutral",
            },
            {
                "id": uuid4(),
                "run_id": constraint_run_b.id,
                "message_id": response_message_id,
                "rating": FeedbackRating.NEGATIVE.value,
                "comment": "x" * 1001,
            },
            {
                "id": uuid4(),
                "run_id": constraint_run_a.id,
                "message_id": response_message_id,
                "rating": FeedbackRating.NEGATIVE.value,
            },
        )
        for row in invalid_rows:
            async with database.session_factory() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(insert(AIFeedback.__table__).values(**row))
                    await session.commit()
                await session.rollback()
    finally:
        async with database.session_factory() as session:
            await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Role).where(Role.tenant_id.in_(tenant_ids)))
            await session.commit()
            remaining = await session.scalar(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.run_id.in_(tracked_run_ids))
            )
            assert remaining == 0
        await database.close()
