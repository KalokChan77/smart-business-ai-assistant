"""Run disposable authenticated AI-feedback smoke tests without model calls."""

import asyncio
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.ai.models import AIRun, AIRunStatus
from app.ai.repository import AIRunsRepository
from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.conversations.models import Conversation, MessageRole
from app.conversations.repository import ConversationsRepository
from app.conversations.schemas import ConversationCreateRequest
from app.conversations.service import ConversationService
from app.core.asyncio_compat import run_async
from app.core.config import Settings
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


def assert_safe_response(
    response: httpx.Response,
    protected_values: tuple[str, ...],
) -> dict[str, object]:
    if any(value and value in response.text for value in protected_values):
        raise AssertionError("A protected server value appeared in a response.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Response payload is not an object.")
    return payload


def require_error_code(payload: dict[str, object]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        raise AssertionError("Error response has no error object.")
    code = error.get("code")
    if not isinstance(code, str):
        raise AssertionError("Error response has no stable code.")
    return code


async def create_feedback_runs(
    database: Database,
    *,
    tenant_id: UUID,
    user_id: UUID,
    username: str,
    email: str,
    suffix: str,
) -> tuple[AIRun, AIRun]:
    principal = Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        username=username,
        email=email,
        roles=frozenset({"admin"}),
    )
    async with database.session_factory() as session:
        conversations = ConversationService(ConversationsRepository(session))
        conversation = await conversations.create(
            principal,
            ConversationCreateRequest(title="反馈冒烟测试"),
        )
        prompt = await conversations.append_message(
            principal,
            conversation.id,
            role=MessageRole.USER,
            content="反馈冒烟问题",
        )
        answer = await conversations.append_message(
            principal,
            conversation.id,
            role=MessageRole.ASSISTANT,
            content="反馈冒烟回答",
        )

    async with database.session_factory() as session:
        runs = AIRunsRepository(session)
        completed = AIRun(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation.id,
            request_id=f"feedback-smoke-completed-{suffix}",
            provider="deepseek",
            model="deepseek-chat",
            status=AIRunStatus.SUCCEEDED,
            prompt_message_id=prompt.id,
            response_message_id=answer.id,
            completed_at=datetime.now(UTC),
        )
        await runs.create(completed)
        running = AIRun(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation.id,
            request_id=f"feedback-smoke-running-{suffix}",
            provider="deepseek",
            model="deepseek-chat",
            status=AIRunStatus.RUNNING,
        )
        await runs.create(running)
        return completed, running


async def fixture_counts(
    database: Database,
    tenant_ids: tuple[UUID, ...],
    feedback_id: UUID | None,
    run_ids: tuple[UUID, ...],
) -> tuple[int, int, int, int, int]:
    async with database.session_factory() as session:
        feedback_count = 0
        if feedback_id is not None:
            feedback_count = await session.scalar(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.id == feedback_id)
            )
        run_count = await session.scalar(
            select(func.count()).select_from(AIRun).where(AIRun.id.in_(run_ids))
        )
        conversation_count = await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.tenant_id.in_(tenant_ids))
        )
        user_count = await session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id.in_(tenant_ids))
        )
        role_count = await session.scalar(
            select(func.count()).select_from(Role).where(Role.tenant_id.in_(tenant_ids))
        )
    return (
        int(feedback_count or 0),
        int(run_count or 0),
        int(conversation_count or 0),
        int(user_count or 0),
        int(role_count or 0),
    )


async def verify() -> None:
    settings = Settings()
    database_url = require_secret(settings.database_url, "DATABASE_URL")
    redis_url = require_secret(settings.redis_url, "REDIS_URL")
    jwt_secret = require_secret(settings.jwt_secret_key, "JWT_SECRET_KEY")
    protected_values = tuple(
        value.get_secret_value().strip()
        for field_name in settings.__class__.model_fields
        if isinstance((value := getattr(settings, field_name)), SecretStr)
        and value.get_secret_value().strip()
    )

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
    tenant_id = uuid4()
    outsider_tenant_id = uuid4()
    tenant_ids = (tenant_id, outsider_tenant_id)
    suffix = uuid4().hex[:8]
    password = secrets.token_urlsafe(24)
    same_tenant_password = secrets.token_urlsafe(24)
    outsider_password = secrets.token_urlsafe(24)
    issued_tokens: list[tuple[str, TokenType]] = []
    redis_keys: set[str] = set()
    feedback_id: UUID | None = None
    run_ids: tuple[UUID, ...] = ()

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            owner = await users.bootstrap_admin(
                tenant_id=tenant_id,
                username=f"feedback-smoke-{suffix}",
                email=f"feedback-smoke-{suffix}@example.test",
                password=password,
            )
        owner_principal = Principal(
            user_id=owner.id,
            tenant_id=tenant_id,
            username=owner.username,
            email=owner.email,
            roles=frozenset({"admin"}),
        )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            same_tenant_user = await users.create_user(
                owner_principal,
                UserCreateRequest(
                    username=f"feedback-peer-{suffix}",
                    email=f"feedback-peer-{suffix}@example.test",
                    password=same_tenant_password,
                    role_codes={"user"},
                ),
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            outsider = await users.bootstrap_admin(
                tenant_id=outsider_tenant_id,
                username=f"feedback-outsider-{suffix}",
                email=f"feedback-outsider-{suffix}@example.test",
                password=outsider_password,
            )

        completed, running = await create_feedback_runs(
            database,
            tenant_id=tenant_id,
            user_id=owner.id,
            username=owner.username,
            email=owner.email,
            suffix=suffix,
        )
        run_ids = (completed.id, running.id)
        completed_message_id = completed.response_message_id
        assert completed_message_id is not None

        base_url = os.getenv("FEEDBACK_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=30,
            trust_env=False,
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(tenant_id),
                    "username": owner.username,
                    "password": password,
                },
            )
            require_status(login, 200, "owner login")
            owner_pair = login.json()
            issued_tokens.extend(
                [
                    (str(owner_pair["access_token"]), TokenType.ACCESS),
                    (str(owner_pair["refresh_token"]), TokenType.REFRESH),
                ]
            )
            owner_headers = {
                "Authorization": f"Bearer {owner_pair['access_token']}"
            }

            same_tenant_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(tenant_id),
                    "username": same_tenant_user.username,
                    "password": same_tenant_password,
                },
            )
            require_status(same_tenant_login, 200, "same-tenant user login")
            same_tenant_pair = same_tenant_login.json()
            issued_tokens.extend(
                [
                    (str(same_tenant_pair["access_token"]), TokenType.ACCESS),
                    (str(same_tenant_pair["refresh_token"]), TokenType.REFRESH),
                ]
            )
            same_tenant_headers = {
                "Authorization": f"Bearer {same_tenant_pair['access_token']}"
            }

            outsider_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(outsider_tenant_id),
                    "username": outsider.username,
                    "password": outsider_password,
                },
            )
            require_status(outsider_login, 200, "outsider login")
            outsider_pair = outsider_login.json()
            issued_tokens.extend(
                [
                    (str(outsider_pair["access_token"]), TokenType.ACCESS),
                    (str(outsider_pair["refresh_token"]), TokenType.REFRESH),
                ]
            )
            outsider_headers = {
                "Authorization": f"Bearer {outsider_pair['access_token']}"
            }
            feedback_protected_values = tuple(
                value
                for value in (
                    *protected_values,
                    password,
                    same_tenant_password,
                    outsider_password,
                    str(owner_pair["access_token"]),
                    str(owner_pair["refresh_token"]),
                    str(same_tenant_pair["access_token"]),
                    str(same_tenant_pair["refresh_token"]),
                    str(outsider_pair["access_token"]),
                    str(outsider_pair["refresh_token"]),
                )
                if value
            )

            created = await client.post(
                f"/api/v1/ai/runs/{completed.id}/feedback",
                headers=owner_headers,
                json={
                    "rating": "negative",
                    "comment": "  冒烟测试负面反馈。  ",
                },
            )
            require_status(created, 200, "feedback create")
            created_payload = assert_safe_response(created, feedback_protected_values)
            if (
                created_payload.get("rating") != FeedbackRating.NEGATIVE.value
                or created_payload.get("comment") != "冒烟测试负面反馈。"
                or created_payload.get("run_id") != str(completed.id)
                or created_payload.get("message_id") != str(completed_message_id)
            ):
                raise AssertionError("Created feedback response is inconsistent.")
            feedback_id = UUID(str(created_payload["id"]))
            if {"tenant_id", "user_id"}.intersection(created_payload):
                raise AssertionError("Feedback response exposed owner internals.")
            print("feedback_create: PASS (status=200, rating=negative)")

            updated = await client.post(
                f"/api/v1/ai/runs/{completed.id}/feedback",
                headers=owner_headers,
                json={"rating": "positive", "comment": "   "},
            )
            require_status(updated, 200, "feedback update")
            updated_payload = assert_safe_response(updated, feedback_protected_values)
            if (
                updated_payload.get("id") != created_payload.get("id")
                or updated_payload.get("rating") != FeedbackRating.POSITIVE.value
                or updated_payload.get("comment") is not None
            ):
                raise AssertionError("Feedback upsert did not preserve one current record.")
            print("feedback_update: PASS (status=200, rating=positive)")

            same_tenant_response = await client.post(
                f"/api/v1/ai/runs/{completed.id}/feedback",
                headers=same_tenant_headers,
                json={"rating": "negative"},
            )
            require_status(
                same_tenant_response,
                404,
                "same-tenant feedback isolation",
            )
            same_tenant_payload = assert_safe_response(
                same_tenant_response,
                feedback_protected_values,
            )
            if require_error_code(same_tenant_payload) != "ai_run_not_found":
                raise AssertionError(
                    "Same-tenant horizontal feedback access was not hidden."
                )
            print("feedback_user_isolation: PASS (peer=not_found)")

            outsider_response = await client.post(
                f"/api/v1/ai/runs/{completed.id}/feedback",
                headers=outsider_headers,
                json={"rating": "negative"},
            )
            require_status(outsider_response, 404, "feedback tenant isolation")
            outsider_payload = assert_safe_response(
                outsider_response,
                feedback_protected_values,
            )
            if require_error_code(outsider_payload) != "ai_run_not_found":
                raise AssertionError("Cross-tenant feedback did not use not-found semantics.")
            print("feedback_tenant_isolation: PASS (outsider=not_found)")

            running_response = await client.post(
                f"/api/v1/ai/runs/{running.id}/feedback",
                headers=owner_headers,
                json={"rating": "negative"},
            )
            require_status(running_response, 409, "unfinished run rejection")
            running_payload = assert_safe_response(
                running_response,
                feedback_protected_values,
            )
            if require_error_code(running_payload) != "ai_run_not_feedbackable":
                raise AssertionError("Unfinished Run did not use the stable error code.")
            print("feedback_unfinished_rejection: PASS (status=409)")

            async with database.session_factory() as session:
                feedback_rows = (
                    await session.execute(
                        select(AIFeedback).where(AIFeedback.run_id == completed.id)
                    )
                ).scalars().all()
                if (
                    len(feedback_rows) != 1
                    or feedback_rows[0].rating != FeedbackRating.POSITIVE
                    or feedback_rows[0].message_id != completed_message_id
                ):
                    raise AssertionError("Persisted feedback state is inconsistent.")

            await client.post(
                "/api/v1/auth/logout",
                headers=owner_headers,
                json={"refresh_token": owner_pair["refresh_token"]},
            )
            await client.post(
                "/api/v1/auth/logout",
                headers=same_tenant_headers,
                json={"refresh_token": same_tenant_pair["refresh_token"]},
            )
            await client.post(
                "/api/v1/auth/logout",
                headers=outsider_headers,
                json={"refresh_token": outsider_pair["refresh_token"]},
            )
    finally:
        for token, token_type in issued_tokens:
            try:
                claims = tokens.decode(token, expected_type=token_type)
            except Exception:
                continue
            redis_key = f"auth:revoked:{claims.jti}"
            redis_keys.add(redis_key)
            await redis.delete(redis_key)

        async with database.session_factory() as session:
            await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Role).where(Role.tenant_id.in_(tenant_ids)))
            await session.commit()

        counts = await fixture_counts(
            database,
            tenant_ids,
            feedback_id,
            run_ids,
        )
        redis_count = 0
        for key in redis_keys:
            redis_count += int(await redis.exists(key))
        await redis.aclose()
        await database.close()
        if any((*counts, redis_count)):
            raise AssertionError("Temporary feedback smoke fixtures were not fully cleaned.")
        print(
            "temporary feedback smoke fixtures: "
            "feedback=0, runs=0, conversations=0, users=0, roles=0, redis_keys=0"
        )


if __name__ == "__main__":
    run_async(verify())
