"""Run a disposable authenticated analytics and tenant-isolation smoke flow."""

import asyncio
import os
import secrets
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.ai.models import AIRun, AIRunStatus
from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.conversations.models import Conversation, Message, MessageRole
from app.core.asyncio_compat import run_async
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
from app.users.schemas import UserCreateRequest
from app.users.service import UserService


def require_secret(value: SecretStr | None, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"{name} must be configured.")
    return value.get_secret_value().strip()


def require_status(response: httpx.Response, expected: int, stage: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{stage} returned HTTP {response.status_code}.")


def require_object(response: httpx.Response, stage: str) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"{stage} payload is not an object.")
    return payload


async def login(
    client: httpx.AsyncClient,
    *,
    tenant_id: UUID,
    username: str,
    password: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": username,
            "password": password,
        },
    )
    require_status(response, 200, "analytics login")
    return require_object(response, "analytics login")


def auth_headers(pair: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {pair['access_token']}"}


async def seed_analytics_fixtures(
    database: Database,
    *,
    tenant_a: UUID,
    tenant_b: UUID,
    admin_a_id: UUID,
    admin_b_id: UUID,
    first_day: date,
    suffix: str,
) -> None:
    first_at = datetime.combine(first_day, time(hour=8), tzinfo=UTC)
    second_at = first_at + timedelta(days=1)
    third_at = first_at + timedelta(days=2)

    async with database.session_factory() as session:
        session.add_all(
            [
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a_id,
                    assigned_user_id=None,
                    subject="退款多久到账？",
                    description="analytics-private-description-a",
                    status=CustomerTicketStatus.OPEN,
                    category=None,
                    created_at=first_at,
                ),
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a_id,
                    assigned_user_id=admin_a_id,
                    subject="退款多久到账？",
                    description="analytics-private-description-b",
                    status=CustomerTicketStatus.RESOLVED,
                    category=CustomerTicketCategory.REFUND_AFTER_SALES,
                    created_at=second_at,
                ),
                CustomerTicket(
                    tenant_id=tenant_a,
                    requester_user_id=admin_a_id,
                    assigned_user_id=admin_a_id,
                    subject="账号登录失败",
                    description="analytics-private-description-c",
                    status=CustomerTicketStatus.IN_PROGRESS,
                    category=CustomerTicketCategory.ACCOUNT_SECURITY,
                    created_at=second_at + timedelta(hours=1),
                ),
                CustomerTicket(
                    tenant_id=tenant_b,
                    requester_user_id=admin_b_id,
                    assigned_user_id=admin_b_id,
                    subject="退款多久到账？",
                    description="analytics-other-tenant-description",
                    status=CustomerTicketStatus.RESOLVED,
                    category=CustomerTicketCategory.REFUND_AFTER_SALES,
                    created_at=second_at,
                ),
            ]
        )

        conversation_a = Conversation(
            tenant_id=tenant_a,
            user_id=admin_a_id,
            title="Analytics smoke A",
            created_at=first_at,
        )
        conversation_b = Conversation(
            tenant_id=tenant_b,
            user_id=admin_b_id,
            title="Analytics smoke B",
            created_at=first_at,
        )
        session.add_all([conversation_a, conversation_b])
        await session.flush()

        run_specs = [
            (
                tenant_a,
                admin_a_id,
                conversation_a.id,
                AIRunStatus.SUCCEEDED,
                "deepseek",
                "deepseek-chat",
                first_at + timedelta(hours=3),
                1000,
                100,
                200,
                None,
            ),
            (
                tenant_a,
                admin_a_id,
                conversation_a.id,
                AIRunStatus.FAILED,
                "deepseek",
                "deepseek-chat",
                second_at + timedelta(hours=3),
                2000,
                50,
                20,
                "provider_timeout",
            ),
            (
                tenant_a,
                admin_a_id,
                conversation_a.id,
                AIRunStatus.RUNNING,
                "dashscope",
                "qwen-plus",
                third_at,
                None,
                20,
                None,
                None,
            ),
            (
                tenant_b,
                admin_b_id,
                conversation_b.id,
                AIRunStatus.SUCCEEDED,
                "deepseek",
                "deepseek-chat",
                second_at + timedelta(hours=4),
                500,
                999,
                999,
                None,
            ),
        ]
        created_runs: list[AIRun] = []
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
                content="analytics-private-question",
                created_at=started_at,
            )
            assistant_message = Message(
                conversation_id=conversation_id,
                position=index * 2,
                role=MessageRole.ASSISTANT,
                content="analytics-private-answer",
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
                request_id=f"analytics-smoke-{suffix}-{index}",
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
                error_message=(
                    "analytics-private-upstream-error"
                    if run_status == AIRunStatus.FAILED
                    else None
                ),
                started_at=started_at,
                completed_at=completed_at,
                created_at=started_at,
            )
            session.add(run)
            await session.flush()
            created_runs.append(run)

        session.add_all(
            [
                AIFeedback(
                    run_id=created_runs[0].id,
                    message_id=created_runs[0].response_message_id,
                    rating=FeedbackRating.POSITIVE,
                    comment="analytics-private-feedback",
                    created_at=second_at + timedelta(hours=6),
                ),
                AIFeedback(
                    run_id=created_runs[3].id,
                    message_id=created_runs[3].response_message_id,
                    rating=FeedbackRating.POSITIVE,
                    comment="analytics-other-tenant-feedback",
                    created_at=second_at + timedelta(hours=6),
                ),
            ]
        )
        await session.commit()


async def fixture_counts(
    database: Database,
    tenant_ids: tuple[UUID, UUID],
) -> tuple[int, int, int, int, int]:
    async with database.session_factory() as session:
        ticket_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(CustomerTicket)
                    .where(CustomerTicket.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        run_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(AIRun)
                    .where(AIRun.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        conversation_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(Conversation)
                    .where(Conversation.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        user_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        role_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(Role)
                    .where(Role.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        return ticket_count, run_count, conversation_count, user_count, role_count


async def verify() -> None:
    settings = Settings()
    database_url = require_secret(settings.database_url, "DATABASE_URL")
    redis_url = require_secret(settings.redis_url, "REDIS_URL")
    jwt_secret = require_secret(settings.jwt_secret_key, "JWT_SECRET_KEY")
    database = Database.create(database_url)
    redis = create_redis_client(redis_url)
    tokens = JwtTokenService(
        secret=jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_ttl=timedelta(minutes=settings.jwt_access_ttl_minutes),
        refresh_ttl=timedelta(days=settings.jwt_refresh_ttl_days),
    )
    tenant_a = uuid4()
    tenant_b = uuid4()
    tenant_ids = (tenant_a, tenant_b)
    suffix = secrets.token_hex(4)
    admin_password = secrets.token_urlsafe(24)
    decision_password = secrets.token_urlsafe(24)
    user_password = secrets.token_urlsafe(24)
    issued_jtis: set[str] = set()
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=2)

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username=f"analytics-admin-{suffix}",
                email=f"analytics-admin-{suffix}@example.test",
                password=admin_password,
            )
        admin_principal = Principal(
            user_id=admin_a.id,
            tenant_id=tenant_a,
            username=admin_a.username,
            email=admin_a.email,
            roles=frozenset({"admin"}),
        )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            decision = await users.create_user(
                admin_principal,
                UserCreateRequest(
                    username=f"analytics-decision-{suffix}",
                    email=f"analytics-decision-{suffix}@example.test",
                    password=decision_password,
                    role_codes={"decision_maker"},
                ),
            )
            ordinary = await users.create_user(
                admin_principal,
                UserCreateRequest(
                    username=f"analytics-user-{suffix}",
                    email=f"analytics-user-{suffix}@example.test",
                    password=user_password,
                    role_codes={"user"},
                ),
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"analytics-other-{suffix}",
                email=f"analytics-other-{suffix}@example.test",
                password=admin_password,
            )

        await seed_analytics_fixtures(
            database,
            tenant_a=tenant_a,
            tenant_b=tenant_b,
            admin_a_id=admin_a.id,
            admin_b_id=admin_b.id,
            first_day=first_day,
            suffix=suffix,
        )

        base_url = os.getenv("ANALYTICS_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=30,
            trust_env=False,
        ) as client:
            admin_pair = await login(
                client,
                tenant_id=tenant_a,
                username=admin_a.username,
                password=admin_password,
            )
            decision_pair = await login(
                client,
                tenant_id=tenant_a,
                username=decision.username,
                password=decision_password,
            )
            user_pair = await login(
                client,
                tenant_id=tenant_a,
                username=ordinary.username,
                password=user_password,
            )
            for pair in (admin_pair, decision_pair, user_pair):
                issued_jtis.add(
                    tokens.decode(
                        str(pair["access_token"]),
                        expected_type=TokenType.ACCESS,
                    ).jti
                )
                issued_jtis.add(
                    tokens.decode(
                        str(pair["refresh_token"]),
                        expected_type=TokenType.REFRESH,
                    ).jti
                )
            print("analytics_login: PASS (roles=admin,decision_maker,user)")

            params = {
                "start_date": first_day.isoformat(),
                "end_date": today.isoformat(),
            }
            admin_overview = await client.get(
                "/api/v1/analytics/overview",
                headers=auth_headers(admin_pair),
                params=params,
            )
            require_status(admin_overview, 200, "admin analytics overview")
            decision_paths = (
                "/api/v1/analytics/overview",
                "/api/v1/analytics/consultations",
                "/api/v1/analytics/categories",
                "/api/v1/analytics/satisfaction",
                "/api/v1/analytics/ai-runs",
            )
            decision_responses = [
                await client.get(
                    path,
                    headers=auth_headers(decision_pair),
                    params=params,
                )
                for path in decision_paths
            ]
            if any(response.status_code != 200 for response in decision_responses):
                raise AssertionError("A decision-maker analytics endpoint failed.")
            print("analytics_rbac: PASS (admin=200, decision_maker=200)")

            user_response = await client.get(
                "/api/v1/analytics/overview",
                headers=auth_headers(user_pair),
                params=params,
            )
            require_status(user_response, 403, "ordinary user analytics denial")
            invalid_response = await client.get(
                "/api/v1/analytics/overview",
                headers=auth_headers(admin_pair),
                params={**params, "unknown": "analytics-sensitive-marker"},
            )
            require_status(invalid_response, 422, "analytics strict query")
            if "analytics-sensitive-marker" in invalid_response.text:
                raise AssertionError("Rejected analytics query value leaked.")
            print("analytics_validation: PASS (user=403, extra_query=422)")

            overview = require_object(decision_responses[0], "overview")
            consultations = require_object(decision_responses[1], "consultations")
            categories = require_object(decision_responses[2], "categories")
            satisfaction = require_object(decision_responses[3], "satisfaction")
            ai_runs = require_object(decision_responses[4], "ai runs")
            if (
                overview.get("consultation_count") != 3
                or overview.get("resolved_consultation_count") != 1
                or overview.get("human_takeover_count") != 2
                or overview.get("ai_run_count") != 3
                or overview.get("ai_terminal_run_count") != 2
                or overview.get("feedback_count") != 1
            ):
                raise AssertionError("Analytics overview metric values are inconsistent.")
            top_questions = overview.get("top_questions")
            if not isinstance(top_questions, list) or top_questions != [
                {"question": "退款多久到账？", "count": 2}
            ]:
                raise AssertionError("Top-question aggregation is inconsistent.")
            points = consultations.get("points")
            if not isinstance(points, list) or [
                point.get("consultation_count") for point in points
            ] != [1, 2, 0]:
                raise AssertionError("Consultation zero-fill trend is inconsistent.")
            if categories.get("total") != 3:
                raise AssertionError("Category total is inconsistent.")
            if (
                satisfaction.get("feedback_count") != 1
                or satisfaction.get("satisfaction_rate") != 100.0
            ):
                raise AssertionError("Satisfaction metric is inconsistent.")
            if (
                ai_runs.get("total") != 3
                or ai_runs.get("running") != 1
                or ai_runs.get("succeeded") != 1
                or ai_runs.get("failed") != 1
                or ai_runs.get("success_rate") != 50.0
            ):
                raise AssertionError("AI Run metrics are inconsistent.")
            protected_values = (
                str(tenant_a),
                str(tenant_b),
                "analytics-private-description",
                "analytics-private-question",
                "analytics-private-answer",
                "analytics-private-feedback",
                "analytics-private-upstream-error",
            )
            combined = "".join(response.text for response in decision_responses)
            if any(value in combined for value in protected_values):
                raise AssertionError("Analytics response exposed protected detail.")
            print(
                "analytics_metrics: PASS "
                "(consultations=3, ai_runs=3, feedback=1, tenant_isolation=true)"
            )

            for pair in (admin_pair, decision_pair, user_pair):
                logout = await client.post(
                    "/api/v1/auth/logout",
                    headers=auth_headers(pair),
                    json={"refresh_token": pair["refresh_token"]},
                )
                require_status(logout, 204, "analytics logout")
            print("analytics_logout: PASS (status=204)")
    finally:
        redis_keys = {f"auth:revoked:{jti}" for jti in issued_jtis}
        for key in redis_keys:
            await redis.delete(key)
        async with database.session_factory() as session:
            run_ids = select(AIRun.id).where(AIRun.tenant_id.in_(tenant_ids))
            await session.execute(
                delete(AIFeedback).where(AIFeedback.run_id.in_(run_ids))
            )
            await session.execute(
                delete(CustomerTicket).where(CustomerTicket.tenant_id.in_(tenant_ids))
            )
            await session.execute(
                delete(AIRun).where(AIRun.tenant_id.in_(tenant_ids))
            )
            await session.execute(
                delete(Conversation).where(Conversation.tenant_id.in_(tenant_ids))
            )
            await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Role).where(Role.tenant_id.in_(tenant_ids)))
            await session.commit()
        counts = await fixture_counts(database, tenant_ids)
        redis_count = 0
        for key in redis_keys:
            redis_count += int(await redis.exists(key))
        await redis.aclose()
        await database.close()
        print(
            "analytics_temporary_fixtures: "
            f"tickets={counts[0]}, runs={counts[1]}, conversations={counts[2]}, "
            f"users={counts[3]}, roles={counts[4]}, redis_keys={redis_count}"
        )
        if any(counts) or redis_count:
            raise AssertionError("Temporary analytics fixtures were not fully removed.")


if __name__ == "__main__":
    run_async(verify())
