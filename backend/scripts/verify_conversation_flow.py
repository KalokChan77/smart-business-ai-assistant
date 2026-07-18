"""Run a disposable end-to-end conversation persistence smoke test."""

import asyncio
import os
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select

from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.conversations.models import Conversation, Message, MessageRole
from app.conversations.repository import ConversationsRepository
from app.conversations.service import ConversationService
from app.core.config import Settings
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService


def error_code(response: httpx.Response) -> str | None:
    if not response.content:
        return None
    body = response.json()
    return body.get("error", {}).get("code") if isinstance(body, dict) else None


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
    tenant_a = uuid4()
    tenant_b = uuid4()
    password = secrets.token_urlsafe(24)
    issued_tokens: list[tuple[str, TokenType]] = []
    results: list[tuple[str, int, str | None]] = []

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username="conversation-smoke-a",
                email="conversation-smoke-a@example.test",
                password=password,
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username="conversation-smoke-b",
                email="conversation-smoke-b@example.test",
                password=password,
            )

        base_url = os.getenv("CONVERSATION_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=15,
            trust_env=False,
        ) as client:
            async def login(tenant_id, username):
                response = await client.post(
                    "/api/v1/auth/login",
                    json={
                        "tenant_id": str(tenant_id),
                        "username": username,
                        "password": password,
                    },
                )
                response.raise_for_status()
                pair = response.json()
                issued_tokens.extend(
                    [
                        (pair["access_token"], TokenType.ACCESS),
                        (pair["refresh_token"], TokenType.REFRESH),
                    ]
                )
                return pair

            pair_a = await login(tenant_a, admin_a.username)
            pair_b = await login(tenant_b, admin_b.username)
            headers_a = {"Authorization": f"Bearer {pair_a['access_token']}"}
            headers_b = {"Authorization": f"Bearer {pair_b['access_token']}"}

            first = await client.post(
                "/api/v1/conversations",
                headers=headers_a,
                json={"title": "  商务咨询  "},
            )
            results.append(("create_first", first.status_code, error_code(first)))
            first.raise_for_status()
            first_id = first.json()["id"]
            first_uuid = UUID(first_id)
            second = await client.post(
                "/api/v1/conversations",
                headers=headers_a,
                json={},
            )
            results.append(("create_second", second.status_code, error_code(second)))

            listed = await client.get(
                "/api/v1/conversations?limit=1&offset=0",
                headers=headers_a,
            )
            results.append(("list_paginated", listed.status_code, error_code(listed)))
            if listed.json()["total"] != 2 or listed.json()["limit"] != 1:
                raise AssertionError("Conversation pagination response is invalid")

            foreign_detail = await client.get(
                f"/api/v1/conversations/{first_id}",
                headers=headers_b,
            )
            results.append(
                ("cross_tenant_detail", foreign_detail.status_code, error_code(foreign_detail))
            )

            principal_a = Principal(
                user_id=admin_a.id,
                tenant_id=tenant_a,
                username=admin_a.username,
                email=admin_a.email,
                roles=frozenset({"admin"}),
            )
            async with database.session_factory() as session:
                conversations = ConversationService(ConversationsRepository(session))
                await conversations.append_message(
                    principal_a,
                    first_uuid,
                    role=MessageRole.USER,
                    content="请介绍平台能力",
                )
                await conversations.append_message(
                    principal_a,
                    first_uuid,
                    role=MessageRole.ASSISTANT,
                    content="平台支持 AI 对话、知识库和客服辅助。",
                    metadata={"provider": "mock"},
                )

            messages = await client.get(
                f"/api/v1/conversations/{first_id}/messages",
                headers=headers_a,
            )
            results.append(("list_messages", messages.status_code, error_code(messages)))
            if [item["role"] for item in messages.json()["items"]] != [
                "user",
                "assistant",
            ]:
                raise AssertionError("Message order is invalid")

            foreign_messages = await client.get(
                f"/api/v1/conversations/{first_id}/messages",
                headers=headers_b,
            )
            results.append(
                (
                    "cross_tenant_messages",
                    foreign_messages.status_code,
                    error_code(foreign_messages),
                )
            )

            deleted = await client.delete(
                f"/api/v1/conversations/{first_id}",
                headers=headers_a,
            )
            results.append(("soft_delete", deleted.status_code, error_code(deleted)))
            missing = await client.get(
                f"/api/v1/conversations/{first_id}",
                headers=headers_a,
            )
            results.append(("deleted_hidden", missing.status_code, error_code(missing)))
            after_delete = await client.get(
                "/api/v1/conversations",
                headers=headers_a,
            )
            results.append(("list_after_delete", after_delete.status_code, error_code(after_delete)))
            if after_delete.json()["total"] != 1:
                raise AssertionError("Soft-deleted conversation remains visible")

            await client.post(
                "/api/v1/auth/logout",
                headers=headers_a,
                json={"refresh_token": pair_a["refresh_token"]},
            )
            await client.post(
                "/api/v1/auth/logout",
                headers=headers_b,
                json={"refresh_token": pair_b["refresh_token"]},
            )

        async with database.session_factory() as session:
            stored = await session.get(Conversation, first_uuid)
            message_count = await session.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == first_uuid)
            )
            if stored is None or stored.deleted_at is None or int(message_count or 0) != 2:
                raise AssertionError("Soft-delete persistence evidence is invalid")
            print("database_soft_delete: deleted_at_set=True, messages_retained=2")

        expected = {
            "create_first": (201, None),
            "create_second": (201, None),
            "list_paginated": (200, None),
            "cross_tenant_detail": (404, "conversation_not_found"),
            "list_messages": (200, None),
            "cross_tenant_messages": (404, "conversation_not_found"),
            "soft_delete": (204, None),
            "deleted_hidden": (404, "conversation_not_found"),
            "list_after_delete": (200, None),
        }
        for name, status_code, code in results:
            print(f"{name}: status={status_code}, result={code or 'ok'}")
            if (status_code, code) != expected[name]:
                raise AssertionError((name, status_code, code))
    finally:
        for token, token_type in issued_tokens:
            try:
                claims = tokens.decode(token, expected_type=token_type)
            except Exception:
                continue
            await redis.delete(f"auth:revoked:{claims.jti}")
        async with database.session_factory() as session:
            await session.execute(
                delete(User).where(User.tenant_id.in_([tenant_a, tenant_b]))
            )
            await session.execute(
                delete(Role).where(Role.tenant_id.in_([tenant_a, tenant_b]))
            )
            await session.commit()
        await redis.aclose()
        await database.close()
        print("temporary conversation fixtures: cleaned")


if __name__ == "__main__":
    asyncio.run(verify())
