"""Run disposable real-provider SSE smoke tests without printing model content."""

import asyncio
import json
import os
import secrets
from datetime import timedelta
from uuid import uuid4

import httpx
from sqlalchemy import delete

from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
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


async def verify() -> None:
    settings = Settings()
    if settings.database_url is None or settings.redis_url is None:
        raise RuntimeError("DATABASE_URL and REDIS_URL must be configured.")
    if settings.jwt_secret_key is None:
        raise RuntimeError("JWT_SECRET_KEY must be configured.")

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

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin = await users.bootstrap_admin(
                tenant_id=tenant_id,
                username=f"ai-smoke-{suffix}",
                email=f"ai-smoke-{suffix}@example.test",
                password=password,
            )

        base_url = os.getenv("AI_SMOKE_BASE_URL", "http://127.0.0.1:8000")
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

            configured = os.getenv("AI_SMOKE_PROVIDERS")
            if configured is None:
                available: list[str] = []
                if settings.deepseek_api_key is not None and settings.deepseek_api_key.get_secret_value().strip():
                    available.append("deepseek")
                if settings.dashscope_api_key is not None and settings.dashscope_api_key.get_secret_value().strip():
                    available.append("dashscope")
                providers = tuple(available)
            else:
                providers = tuple(
                    item.strip() for item in configured.split(",") if item.strip()
                )
            if not providers:
                raise RuntimeError("No configured AI provider is available for smoke testing.")
            for provider in providers:
                conversation = await client.post(
                    "/api/v1/conversations",
                    headers=headers,
                    json={"title": f"{provider} 冒烟测试"},
                )
                conversation.raise_for_status()
                conversation_id = conversation.json()["id"]
                request_id = f"ai-smoke-{provider}-{suffix}"
                response = await client.post(
                    "/api/v1/ai/chat/stream",
                    headers={**headers, "X-Request-ID": request_id},
                    json={
                        "conversation_id": conversation_id,
                        "message": "请只回复两个大写英文字母：OK",
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
                        f"{provider}: {error.get('code', 'unknown_provider_error')}"
                    )
                if event_names[-1] != "message_end" or "token" not in event_names:
                    raise AssertionError(f"{provider}: invalid SSE terminal sequence")

                metadata = events[0][1]
                run_id = str(metadata["run_id"])
                run = await client.get(f"/api/v1/ai/runs/{run_id}", headers=headers)
                run.raise_for_status()
                if run.json()["status"] != "succeeded":
                    raise AssertionError(f"{provider}: AI run did not succeed")

                messages = await client.get(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    headers=headers,
                )
                messages.raise_for_status()
                items = messages.json()["items"]
                if [item["role"] for item in items] != ["user", "assistant"]:
                    raise AssertionError(f"{provider}: persisted message roles are invalid")
                if not items[-1]["content"].strip():
                    raise AssertionError(f"{provider}: assistant message is empty")
                print(
                    f"{provider}: events={event_names}, "
                    f"assistant_chars={len(items[-1]['content'])}, run=succeeded"
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
            await redis.delete(f"auth:revoked:{claims.jti}")
        async with database.session_factory() as session:
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Role).where(Role.tenant_id == tenant_id))
            await session.commit()
        await redis.aclose()
        await database.close()
        print("temporary AI smoke fixtures: cleaned")


if __name__ == "__main__":
    run_async(verify())
