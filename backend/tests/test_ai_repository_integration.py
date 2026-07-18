from uuid import uuid4

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError

from app.ai.models import AIRun, AIRunMode, AIRunStatus
from app.ai.repository import AIRunsRepository, DuplicateAIRunError
from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.conversations.repository import ConversationsRepository
from app.conversations.schemas import ConversationCreateRequest
from app.conversations.service import ConversationService
from app.core.config import Settings
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService

pytestmark = pytest.mark.integration


async def test_ai_runs_are_owner_scoped_idempotent_and_constrained() -> None:
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
                username=f"ai-run-admin-a-{suffix}",
                email=f"ai-run-admin-a-{suffix}@example.test",
                password="integration-password",
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"ai-run-admin-b-{suffix}",
                email=f"ai-run-admin-b-{suffix}@example.test",
                password="integration-password",
            )

        principal_a = Principal(
            user_id=admin_a.id,
            tenant_id=tenant_a,
            username=admin_a.username,
            email=admin_a.email,
            roles=frozenset({"admin"}),
        )
        principal_b = Principal(
            user_id=admin_b.id,
            tenant_id=tenant_b,
            username=admin_b.username,
            email=admin_b.email,
            roles=frozenset({"admin"}),
        )

        async with database.session_factory() as session:
            conversations = ConversationService(ConversationsRepository(session))
            conversation = await conversations.create(
                principal_a,
                ConversationCreateRequest(title="AI Run 集成测试"),
            )

        async with database.session_factory() as session:
            repository = AIRunsRepository(session)
            run = AIRun(
                tenant_id=tenant_a,
                user_id=admin_a.id,
                conversation_id=conversation.id,
                request_id=f"ai-run-{suffix}",
                provider="deepseek",
                model="deepseek-chat",
                status=AIRunStatus.RUNNING,
            )
            await repository.create(run)
            assert run.mode == AIRunMode.CHAT
            assert (
                await repository.get_owned(
                    tenant_id=principal_a.tenant_id,
                    user_id=principal_a.user_id,
                    run_id=run.id,
                )
                is not None
            )
            assert (
                await repository.get_owned(
                    tenant_id=principal_b.tenant_id,
                    user_id=principal_b.user_id,
                    run_id=run.id,
                )
                is None
            )

            duplicate = AIRun(
                tenant_id=tenant_a,
                user_id=admin_a.id,
                conversation_id=conversation.id,
                request_id=run.request_id,
                provider="deepseek",
                model="deepseek-chat",
            )
            with pytest.raises(DuplicateAIRunError):
                await repository.create(duplicate)

        async with database.session_factory() as session:
            repository = AIRunsRepository(session)
            agent_run = AIRun(
                tenant_id=tenant_a,
                user_id=admin_a.id,
                conversation_id=conversation.id,
                request_id=f"agent-run-{suffix}",
                provider="deepseek",
                model="deepseek-chat",
                mode=AIRunMode.AGENT,
            )
            await repository.create(agent_run)
            assert agent_run.mode == AIRunMode.AGENT

        invalid_rows = (
            {
                "id": uuid4(),
                "tenant_id": tenant_a,
                "user_id": admin_a.id,
                "conversation_id": conversation.id,
                "request_id": f"negative-token-{suffix}",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "status": AIRunStatus.RUNNING.value,
                "input_tokens": -1,
            },
            {
                "id": uuid4(),
                "tenant_id": tenant_a,
                "user_id": admin_a.id,
                "conversation_id": conversation.id,
                "request_id": f"invalid-status-{suffix}",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "status": "unknown",
            },
            {
                "id": uuid4(),
                "tenant_id": tenant_a,
                "user_id": admin_a.id,
                "conversation_id": conversation.id,
                "request_id": f"invalid-mode-{suffix}",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "mode": "unknown",
                "status": AIRunStatus.RUNNING.value,
            },
        )
        for row in invalid_rows:
            async with database.session_factory() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(insert(AIRun.__table__).values(**row))
                    await session.commit()
                await session.rollback()
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
