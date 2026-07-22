"""Run a disposable real-provider Agent SSE smoke test without printing secrets."""

import asyncio
import json
import os
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select

from app.ai.models import AIRun
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.conversations.models import Conversation
from app.core.asyncio_compat import run_async
from app.core.config import Settings
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService


def parse_sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    current_event: str | None = None
    data_lines: list[str] = []
    for line in text.splitlines() + [""]:
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
        elif not line and current_event is not None:
            payload = json.loads("\n".join(data_lines)) if data_lines else {}
            events.append((current_event, payload))
            current_event = None
            data_lines = []
    return events


def configured_providers(settings: Settings) -> tuple[str, ...]:
    configured = os.getenv("AGENT_SMOKE_PROVIDERS")
    if configured is not None:
        return tuple(item.strip() for item in configured.split(",") if item.strip())
    if (
        settings.deepseek_api_key is not None
        and settings.deepseek_api_key.get_secret_value().strip()
    ):
        return ("deepseek",)
    if (
        settings.dashscope_api_key is not None
        and settings.dashscope_api_key.get_secret_value().strip()
    ):
        return ("dashscope",)
    return ()


async def cleanup_counts(database: Database, tenant_id: UUID) -> tuple[int, int, int]:
    async with database.session_factory() as session:
        user_count = await session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        )
        conversation_count = await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.tenant_id == tenant_id)
        )
        run_count = await session.scalar(
            select(func.count()).select_from(AIRun).where(AIRun.tenant_id == tenant_id)
        )
    return int(user_count or 0), int(conversation_count or 0), int(run_count or 0)


async def verify() -> None:
    settings = Settings()
    if settings.database_url is None or settings.redis_url is None:
        raise RuntimeError("DATABASE_URL and REDIS_URL must be configured.")
    if settings.jwt_secret_key is None:
        raise RuntimeError("JWT_SECRET_KEY must be configured.")

    providers = configured_providers(settings)
    if not providers:
        raise RuntimeError("No configured Agent provider is available for smoke testing.")

    database = Database.create(settings.database_url.get_secret_value())
    redis = create_redis_client(settings.redis_url.get_secret_value())
    tokens = JwtTokenService(
        secret=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_ttl=timedelta(minutes=settings.jwt_access_ttl_minutes),
        refresh_ttl=timedelta(days=settings.jwt_refresh_ttl_days),
    )
    tenant_id = uuid4()
    suffix = uuid4().hex[:8]
    password = secrets.token_urlsafe(24)
    issued_tokens: list[tuple[str, TokenType]] = []
    redis_keys: set[str] = set()

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin = await users.bootstrap_admin(
                tenant_id=tenant_id,
                username=f"agent-smoke-{suffix}",
                email=f"agent-smoke-{suffix}@example.test",
                password=password,
            )

        base_url = os.getenv("AGENT_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=180,
            trust_env=False,
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(tenant_id),
                    "username": admin.username,
                    "password": password,
                },
            )
            login.raise_for_status()
            pair = login.json()
            issued_tokens.extend(
                [
                    (pair["access_token"], TokenType.ACCESS),
                    (pair["refresh_token"], TokenType.REFRESH),
                ]
            )
            headers = {"Authorization": f"Bearer {pair['access_token']}"}

            for provider in providers:
                conversation = await client.post(
                    "/api/v1/conversations",
                    headers=headers,
                    json={"title": f"{provider} Agent 冒烟测试"},
                )
                conversation.raise_for_status()
                conversation_id = conversation.json()["id"]
                response = await client.post(
                    "/api/v1/ai/agent/stream",
                    headers={
                        **headers,
                        "X-Request-ID": f"agent-smoke-{provider}-{suffix}",
                    },
                    json={
                        "conversation_id": conversation_id,
                        "message": (
                            "必须调用计算工具计算 12 * 8 + 4，"
                            "然后用一句中文报告计算结果。"
                        ),
                        "provider": provider,
                    },
                )
                response.raise_for_status()
                events = parse_sse(response.text)
                event_names = [name for name, _ in events]
                if not events or event_names[0] != "metadata":
                    raise AssertionError(f"{provider}: metadata event missing")
                if "error" in event_names:
                    error = next(data for name, data in events if name == "error")
                    raise AssertionError(
                        f"{provider}: {error.get('code', 'unknown_agent_error')}"
                    )
                required = ("tool_start", "tool_end", "token", "message_end")
                if any(name not in event_names for name in required):
                    raise AssertionError(f"{provider}: required Agent event missing")
                if not (
                    event_names.index("tool_start")
                    < event_names.index("tool_end")
                    < event_names.index("message_end")
                ):
                    raise AssertionError(f"{provider}: invalid tool event order")
                if event_names[-1] != "message_end":
                    raise AssertionError(f"{provider}: invalid terminal event")

                metadata = events[0][1]
                if metadata.get("mode") != "agent":
                    raise AssertionError(f"{provider}: metadata mode is not agent")
                run_id = str(metadata["run_id"])
                run = await client.get(f"/api/v1/ai/runs/{run_id}", headers=headers)
                run.raise_for_status()
                run_payload = run.json()
                if run_payload["status"] != "succeeded":
                    raise AssertionError(f"{provider}: Agent run did not succeed")
                if run_payload["mode"] != "agent":
                    raise AssertionError(f"{provider}: persisted run mode is not agent")

                messages = await client.get(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    headers=headers,
                )
                messages.raise_for_status()
                items = messages.json()["items"]
                if [item["role"] for item in items] != ["user", "assistant"]:
                    raise AssertionError(
                        f"{provider}: intermediate tool messages were persisted"
                    )
                if not items[-1]["content"].strip():
                    raise AssertionError(f"{provider}: assistant message is empty")
                if items[-1]["metadata"].get("tool_call_count", 0) < 1:
                    raise AssertionError(f"{provider}: tool call metadata missing")
                print(
                    f"{provider}: events={event_names}, "
                    f"assistant_chars={len(items[-1]['content'])}, "
                    "run=agent/succeeded"
                )

            await client.post(
                "/api/v1/auth/logout",
                headers=headers,
                json={"refresh_token": pair["refresh_token"]},
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
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Role).where(Role.tenant_id == tenant_id))
            await session.commit()

        user_count, conversation_count, run_count = await cleanup_counts(
            database, tenant_id
        )
        redis_count = 0
        for key in redis_keys:
            redis_count += int(await redis.exists(key))
        cleanup_failed = any(
            (user_count, conversation_count, run_count, redis_count)
        )
        await redis.aclose()
        await database.close()
        if cleanup_failed:
            raise AssertionError("Temporary Agent smoke fixtures were not fully cleaned.")
        print(
            "temporary Agent smoke fixtures: "
            "users=0, conversations=0, runs=0, redis_keys=0"
        )


if __name__ == "__main__":
    run_async(verify())
