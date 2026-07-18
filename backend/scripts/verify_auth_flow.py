"""Run a disposable end-to-end authentication and tenant-isolation smoke test."""

import asyncio
import os
import secrets
from datetime import timedelta
from uuid import uuid4

import httpx
from sqlalchemy import delete

from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.core.config import Settings
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService


def error_code(response: httpx.Response) -> str | None:
    if not response.content:
        return None
    try:
        body = response.json()
    except ValueError:
        return "non_json_response"
    if isinstance(body, dict):
        return body.get("error", {}).get("code")
    return None


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
                username="smoke-admin-a",
                email="smoke-admin-a@example.test",
                password=password,
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username="smoke-admin-b",
                email="smoke-admin-b@example.test",
                password=password,
            )

        base_url = os.getenv("AUTH_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=15,
            trust_env=False,
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(tenant_a),
                    "username": admin_a.username,
                    "password": password,
                },
            )
            results.append(("login", login.status_code, error_code(login)))
            login.raise_for_status()
            first_pair = login.json()
            access_one = first_pair["access_token"]
            refresh_one = first_pair["refresh_token"]
            issued_tokens.extend(
                [
                    (access_one, TokenType.ACCESS),
                    (refresh_one, TokenType.REFRESH),
                ]
            )
            first_headers = {"Authorization": f"Bearer {access_one}"}

            me = await client.get("/api/v1/auth/me", headers=first_headers)
            results.append(("me", me.status_code, error_code(me)))
            listed = await client.get("/api/v1/users", headers=first_headers)
            results.append(("list_users", listed.status_code, error_code(listed)))
            cross_tenant = await client.patch(
                f"/api/v1/users/{admin_b.id}",
                headers=first_headers,
                json={"status": "disabled"},
            )
            results.append(
                ("cross_tenant_block", cross_tenant.status_code, error_code(cross_tenant))
            )

            created = await client.post(
                "/api/v1/users",
                headers=first_headers,
                json={
                    "username": "smoke-created-user",
                    "email": "smoke-created-user@example.test",
                    "password": "temporary-test-password",
                    "role_codes": ["admin"],
                },
            )
            results.append(("create_user", created.status_code, error_code(created)))
            created.raise_for_status()
            delegated_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(tenant_a),
                    "username": "smoke-created-user",
                    "password": "temporary-test-password",
                },
            )
            results.append(
                ("delegated_admin_login", delegated_login.status_code, error_code(delegated_login))
            )
            delegated_login.raise_for_status()
            delegated_pair = delegated_login.json()
            delegated_access = delegated_pair["access_token"]
            delegated_refresh = delegated_pair["refresh_token"]
            issued_tokens.extend(
                [
                    (delegated_access, TokenType.ACCESS),
                    (delegated_refresh, TokenType.REFRESH),
                ]
            )
            delegated_headers = {"Authorization": f"Bearer {delegated_access}"}

            role_updated = await client.patch(
                f"/api/v1/users/{created.json()['id']}",
                headers=first_headers,
                json={"role_codes": ["user"]},
            )
            results.append(
                ("downgrade_user_role", role_updated.status_code, error_code(role_updated))
            )
            stale_role_access = await client.get(
                "/api/v1/users", headers=delegated_headers
            )
            results.append(
                (
                    "database_role_overrides_jwt",
                    stale_role_access.status_code,
                    error_code(stale_role_access),
                )
            )

            updated = await client.patch(
                f"/api/v1/users/{created.json()['id']}",
                headers=first_headers,
                json={"status": "disabled"},
            )
            results.append(("disable_user", updated.status_code, error_code(updated)))
            disabled_access = await client.get(
                "/api/v1/auth/me", headers=delegated_headers
            )
            results.append(
                (
                    "disabled_user_token_block",
                    disabled_access.status_code,
                    error_code(disabled_access),
                )
            )

            refreshed = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_one},
            )
            results.append(("refresh", refreshed.status_code, error_code(refreshed)))
            refreshed.raise_for_status()
            second_pair = refreshed.json()
            access_two = second_pair["access_token"]
            refresh_two = second_pair["refresh_token"]
            issued_tokens.extend(
                [
                    (access_two, TokenType.ACCESS),
                    (refresh_two, TokenType.REFRESH),
                ]
            )

            consumed_claims = tokens.decode(
                refresh_one, expected_type=TokenType.REFRESH
            )
            consumed_key = f"auth:revoked:{consumed_claims.jti}"
            consumed_value = await redis.get(consumed_key)
            consumed_ttl = await redis.ttl(consumed_key)
            if consumed_value != "1" or consumed_ttl <= 0:
                raise AssertionError("Redis refresh revocation marker is invalid")
            print(
                f"redis_refresh_revocation: ttl_positive={consumed_ttl > 0}, value_is_marker={consumed_value == '1'}"
            )

            replay = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_one},
            )
            results.append(
                ("refresh_replay_block", replay.status_code, error_code(replay))
            )
            old_logout = await client.post(
                "/api/v1/auth/logout",
                headers=first_headers,
                json={"refresh_token": refresh_one},
            )
            results.append(("logout_old_pair", old_logout.status_code, error_code(old_logout)))
            old_me = await client.get("/api/v1/auth/me", headers=first_headers)
            results.append(
                ("old_access_revoked", old_me.status_code, error_code(old_me))
            )

            second_headers = {"Authorization": f"Bearer {access_two}"}
            rotated_me = await client.get("/api/v1/auth/me", headers=second_headers)
            results.append(
                ("rotated_access", rotated_me.status_code, error_code(rotated_me))
            )
            logout = await client.post(
                "/api/v1/auth/logout",
                headers=second_headers,
                json={"refresh_token": refresh_two},
            )
            results.append(("logout", logout.status_code, error_code(logout)))
            revoked = await client.get("/api/v1/auth/me", headers=second_headers)
            results.append(
                ("revoked_access_block", revoked.status_code, error_code(revoked))
            )
            openapi = await client.get("/openapi.json")
            version = (
                openapi.json()["info"]["version"]
                if openapi.status_code == 200
                else error_code(openapi)
            )
            results.append(("openapi", openapi.status_code, version))

        expected = {
            "login": (200, None),
            "me": (200, None),
            "list_users": (200, None),
            "cross_tenant_block": (404, "user_not_found"),
            "create_user": (201, None),
            "delegated_admin_login": (200, None),
            "downgrade_user_role": (200, None),
            "database_role_overrides_jwt": (403, "forbidden"),
            "disable_user": (200, None),
            "disabled_user_token_block": (403, "user_disabled"),
            "refresh": (200, None),
            "refresh_replay_block": (401, "invalid_token"),
            "logout_old_pair": (204, None),
            "old_access_revoked": (401, "invalid_token"),
            "rotated_access": (200, None),
            "logout": (204, None),
            "revoked_access_block": (401, "invalid_token"),
            "openapi": (200, "0.4.0"),
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
        print("temporary auth fixtures: cleaned")


if __name__ == "__main__":
    asyncio.run(verify())
