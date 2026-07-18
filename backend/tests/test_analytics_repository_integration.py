from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.ai.models import AIRun, AIRunStatus
from app.analytics.repository import SQLAlchemyAnalyticsRepository
from app.conversations.models import Conversation, Message, MessageRole
from app.core.config import Settings
from app.customer_service.models import (
    CustomerTicket,
    CustomerTicketCategory,
    CustomerTicketStatus,
)
from app.db.session import Database
from app.feedback.models import AIFeedback, FeedbackRating
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService
from app.auth.security import PasswordService

pytestmark = pytest.mark.integration


async def test_analytics_repository_aggregates_current_tenant_only() -> None:
    settings = Settings()
    assert settings.database_url is not None
    database = Database.create(settings.database_url.get_secret_value())
    tenant_a = uuid4()
    tenant_b = uuid4()
    suffix = uuid4().hex[:8]
    start_at = datetime(2026, 7, 15, tzinfo=UTC)
    end_at = datetime(2026, 7, 18, tzinfo=UTC)

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username=f"analytics-a-{suffix}",
                email=f"analytics-a-{suffix}@example.test",
                password="integration-password",
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"analytics-b-{suffix}",
                email=f"analytics-b-{suffix}@example.test",
                password="integration-password",
            )

        async with database.session_factory() as session:
            tickets = [
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a.id,
                    assigned_user_id=None,
                    subject="退款多久到账？",
                    description="第一条重复问题",
                    status=CustomerTicketStatus.OPEN,
                    category=None,
                    created_at=start_at,
                ),
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a.id,
                    assigned_user_id=admin_a.id,
                    subject="退款多久到账？",
                    description="第二条重复问题",
                    status=CustomerTicketStatus.RESOLVED,
                    category=CustomerTicketCategory.REFUND_AFTER_SALES,
                    created_at=datetime(2026, 7, 16, 9, tzinfo=UTC),
                ),
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a.id,
                    assigned_user_id=admin_a.id,
                    subject="账号登录失败",
                    description="账号问题",
                    status=CustomerTicketStatus.IN_PROGRESS,
                    category=CustomerTicketCategory.ACCOUNT_SECURITY,
                    created_at=datetime(2026, 7, 16, 10, tzinfo=UTC),
                ),
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a.id,
                    assigned_user_id=admin_a.id,
                    subject="范围外问题",
                    description="不应进入统计",
                    status=CustomerTicketStatus.RESOLVED,
                    category=CustomerTicketCategory.OTHER,
                    created_at=datetime(2026, 7, 14, 23, 59, tzinfo=UTC),
                ),
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a.id,
                    assigned_user_id=admin_a.id,
                    subject="结束边界问题",
                    description="结束时间为开区间，不应进入统计",
                    status=CustomerTicketStatus.RESOLVED,
                    category=CustomerTicketCategory.OTHER,
                    created_at=end_at,
                ),
                CustomerTicket(
                    tenant_id=tenant_b,
                    requester_user_id=admin_b.id,
                    assigned_user_id=admin_b.id,
                    subject="退款多久到账？",
                    description="其他租户数据",
                    status=CustomerTicketStatus.RESOLVED,
                    category=CustomerTicketCategory.REFUND_AFTER_SALES,
                    created_at=datetime(2026, 7, 16, 11, tzinfo=UTC),
                ),
            ]
            session.add_all(tickets)

            conversation_a = Conversation(
                tenant_id=tenant_a,
                user_id=admin_a.id,
                title="统计集成测试 A",
                created_at=datetime(2026, 7, 15, 7, tzinfo=UTC),
            )
            conversation_b = Conversation(
                tenant_id=tenant_b,
                user_id=admin_b.id,
                title="统计集成测试 B",
                created_at=datetime(2026, 7, 15, 7, tzinfo=UTC),
            )
            session.add_all([conversation_a, conversation_b])
            await session.flush()

            messages = []
            runs = []
            run_specs = [
                (
                    tenant_a,
                    admin_a.id,
                    conversation_a.id,
                    AIRunStatus.SUCCEEDED,
                    "deepseek",
                    "deepseek-chat",
                    datetime(2026, 7, 15, 12, tzinfo=UTC),
                    1000,
                    100,
                    200,
                    None,
                ),
                (
                    tenant_a,
                    admin_a.id,
                    conversation_a.id,
                    AIRunStatus.FAILED,
                    "deepseek",
                    "deepseek-chat",
                    datetime(2026, 7, 16, 12, tzinfo=UTC),
                    2000,
                    50,
                    20,
                    "provider_timeout",
                ),
                (
                    tenant_a,
                    admin_a.id,
                    conversation_a.id,
                    AIRunStatus.CANCELLED,
                    "dashscope",
                    "qwen-plus",
                    datetime(2026, 7, 16, 13, tzinfo=UTC),
                    500,
                    None,
                    None,
                    None,
                ),
                (
                    tenant_a,
                    admin_a.id,
                    conversation_a.id,
                    AIRunStatus.RUNNING,
                    "dashscope",
                    "qwen-plus",
                    datetime(2026, 7, 17, 8, tzinfo=UTC),
                    None,
                    20,
                    None,
                    None,
                ),
                (
                    tenant_a,
                    admin_a.id,
                    conversation_a.id,
                    AIRunStatus.SUCCEEDED,
                    "dashscope",
                    "qwen-plus",
                    datetime(2026, 7, 17, 9, tzinfo=UTC),
                    1500,
                    80,
                    180,
                    None,
                ),
                (
                    tenant_b,
                    admin_b.id,
                    conversation_b.id,
                    AIRunStatus.SUCCEEDED,
                    "deepseek",
                    "deepseek-chat",
                    datetime(2026, 7, 16, 14, tzinfo=UTC),
                    900,
                    999,
                    999,
                    None,
                ),
            ]
            for index, spec in enumerate(run_specs, start=1):
                (
                    tenant_id,
                    user_id,
                    conversation_id,
                    run_status,
                    provider,
                    model,
                    started_at,
                    duration_ms,
                    input_tokens,
                    output_tokens,
                    error_code,
                ) = spec
                user_message = Message(
                    conversation_id=conversation_id,
                    position=index * 2 - 1,
                    role=MessageRole.USER,
                    content="统计测试问题",
                    created_at=started_at,
                )
                assistant_message = Message(
                    conversation_id=conversation_id,
                    position=index * 2,
                    role=MessageRole.ASSISTANT,
                    content="统计测试回答",
                    created_at=started_at,
                )
                session.add_all([user_message, assistant_message])
                await session.flush()
                completed_at = (
                    started_at + timedelta(milliseconds=duration_ms)
                    if duration_ms is not None
                    else None
                )
                run = AIRun(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    request_id=f"analytics-run-{suffix}-{index}",
                    provider=provider,
                    model=model,
                    status=run_status,
                    prompt_message_id=user_message.id,
                    response_message_id=(
                        assistant_message.id
                        if run_status == AIRunStatus.SUCCEEDED
                        else None
                    ),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error_code=error_code,
                    started_at=started_at,
                    completed_at=completed_at,
                    created_at=started_at,
                )
                session.add(run)
                await session.flush()
                messages.append((user_message, assistant_message))
                runs.append(run)

            session.add_all(
                [
                    AIFeedback(
                        run_id=runs[0].id,
                        message_id=runs[0].response_message_id,
                        rating=FeedbackRating.POSITIVE,
                        comment=None,
                        created_at=datetime(2026, 7, 16, 15, tzinfo=UTC),
                    ),
                    AIFeedback(
                        run_id=runs[4].id,
                        message_id=runs[4].response_message_id,
                        rating=FeedbackRating.NEGATIVE,
                        comment=None,
                        created_at=datetime(2026, 7, 17, 15, tzinfo=UTC),
                    ),
                    AIFeedback(
                        run_id=runs[5].id,
                        message_id=runs[5].response_message_id,
                        rating=FeedbackRating.POSITIVE,
                        comment=None,
                        created_at=datetime(2026, 7, 16, 16, tzinfo=UTC),
                    ),
                ]
            )
            await session.commit()

        async with database.session_factory() as session:
            repository = SQLAlchemyAnalyticsRepository(session)
            tickets = await repository.get_ticket_summary(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
            )
            daily = await repository.get_daily_consultations(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
            )
            categories = await repository.get_category_distribution(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
            )
            satisfaction = await repository.get_satisfaction_summary(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
            )
            top_questions = await repository.get_top_questions(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
                limit=5,
            )
            ai_runs = await repository.get_ai_run_summary(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
            )

        assert tickets == type(tickets)(total=3, resolved=1, human_takeover=2)
        assert [(item.day, item.total) for item in daily] == [
            (datetime(2026, 7, 15, tzinfo=UTC).date(), 1),
            (datetime(2026, 7, 16, tzinfo=UTC).date(), 2),
        ]
        assert sum(item.count for item in categories) == 3
        assert {item.category: item.count for item in categories}[None] == 1
        assert satisfaction.total == 2
        assert satisfaction.positive == 1
        assert satisfaction.negative == 1
        assert top_questions[0].question == "退款多久到账？"
        assert top_questions[0].count == 2
        assert ai_runs.total == 5
        assert ai_runs.running == 1
        assert ai_runs.succeeded == 2
        assert ai_runs.failed == 1
        assert ai_runs.cancelled == 1
        assert ai_runs.average_duration_ms == pytest.approx(1250.0)
        assert ai_runs.average_input_tokens == pytest.approx(62.5)
        assert ai_runs.average_output_tokens == pytest.approx(400 / 3)
        assert [(item.provider, item.model, item.total) for item in ai_runs.by_model] == [
            ("dashscope", "qwen-plus", 3),
            ("deepseek", "deepseek-chat", 2),
        ]
        assert [(item.code, item.count) for item in ai_runs.errors] == [
            ("provider_timeout", 1)
        ]

        async with database.session_factory() as session:
            session.add(
                AIRun(
                    tenant_id=tenant_a,
                    user_id=admin_a.id,
                    conversation_id=conversation_a.id,
                    request_id=f"analytics-run-{suffix}-unknown-error",
                    provider="deepseek",
                    model="deepseek-chat",
                    status=AIRunStatus.FAILED,
                    error_code=None,
                    started_at=datetime(2026, 7, 17, 10, tzinfo=UTC),
                    completed_at=datetime(2026, 7, 17, 10, 0, 1, tzinfo=UTC),
                    created_at=datetime(2026, 7, 17, 10, tzinfo=UTC),
                )
            )
            await session.commit()

        async with database.session_factory() as session:
            repository = SQLAlchemyAnalyticsRepository(session)
            ai_runs_with_unknown_error = await repository.get_ai_run_summary(
                tenant_id=tenant_a,
                start_at=start_at,
                end_at=end_at,
            )

        assert [(item.code, item.count) for item in ai_runs_with_unknown_error.errors] == [
            ("provider_timeout", 1),
            ("unknown", 1),
        ]
    finally:
        async with database.session_factory() as session:
            await session.execute(
                delete(AIFeedback).where(
                    AIFeedback.run_id.in_(
                        select(AIRun.id).where(AIRun.tenant_id.in_([tenant_a, tenant_b]))
                    )
                )
            )
            await session.execute(delete(CustomerTicket).where(CustomerTicket.tenant_id.in_([tenant_a, tenant_b])))
            await session.execute(delete(AIRun).where(AIRun.tenant_id.in_([tenant_a, tenant_b])))
            await session.execute(delete(Conversation).where(Conversation.tenant_id.in_([tenant_a, tenant_b])))
            await session.execute(delete(User).where(User.tenant_id.in_([tenant_a, tenant_b])))
            await session.execute(delete(Role).where(Role.tenant_id.in_([tenant_a, tenant_b])))
            await session.commit()
        await database.close()
