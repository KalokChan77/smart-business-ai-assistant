"""Run a disposable authenticated FastAPI-to-Dify TTS smoke flow."""

import asyncio
import io
import os
import secrets
import wave
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.core.asyncio_compat import run_async
from app.core.config import Settings
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService


def require_secret(value: SecretStr | None, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"{name} must be configured.")
    return value.get_secret_value().strip()


def require_status(response: httpx.Response, expected: int, stage: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{stage} returned HTTP {response.status_code}.")


def validate_audio(response: httpx.Response, max_bytes: int) -> str:
    media_type = response.headers.get("content-type", "").split(";", 1)[0]
    content = response.content
    if not content or len(content) > max_bytes:
        raise AssertionError("TTS response size is invalid.")

    if media_type == "audio/wav":
        if not (content.startswith(b"RIFF") and content[8:12] == b"WAVE"):
            raise AssertionError("WAV response has an invalid signature.")
        with wave.open(io.BytesIO(content), "rb") as audio:
            if audio.getnchannels() <= 0 or audio.getnframes() <= 0:
                raise AssertionError("WAV response contains no playable frames.")
        return "wav"

    if media_type == "audio/mpeg":
        is_mp3 = content.startswith(b"ID3") or (
            len(content) >= 2
            and content[0] == 0xFF
            and (content[1] & 0xE0) == 0xE0
        )
        if not is_mp3:
            raise AssertionError("MP3 response has an invalid signature.")
        return "mp3"

    raise AssertionError("TTS response has an unsupported media type.")


async def fixture_counts(database: Database, tenant_id: UUID) -> tuple[int, int]:
    async with database.session_factory() as session:
        user_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.tenant_id == tenant_id)
                )
            )
            or 0
        )
        role_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(Role)
                    .where(Role.tenant_id == tenant_id)
                )
            )
            or 0
        )
        return user_count, role_count


async def verify() -> None:
    settings = Settings()
    database_url = require_secret(settings.database_url, "DATABASE_URL")
    redis_url = require_secret(settings.redis_url, "REDIS_URL")
    jwt_secret = require_secret(settings.jwt_secret_key, "JWT_SECRET_KEY")
    require_secret(settings.dify_chat_app_api_key, "DIFY_CHAT_APP_API_KEY")

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
    suffix = secrets.token_hex(4)
    username = f"tts-smoke-{suffix}"
    password = secrets.token_urlsafe(24)
    issued_jtis: set[str] = set()

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            await users.bootstrap_admin(
                tenant_id=tenant_id,
                username=username,
                email=f"{username}@example.test",
                password=password,
            )

        base_url = os.getenv("TTS_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        timeout = max(30.0, settings.dify_tts_timeout_seconds + 15.0)
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            trust_env=False,
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(tenant_id),
                    "username": username,
                    "password": password,
                },
            )
            require_status(login, 200, "login")
            pair = login.json()
            access_token = str(pair["access_token"])
            refresh_token = str(pair["refresh_token"])
            issued_jtis.add(
                tokens.decode(
                    access_token,
                    expected_type=TokenType.ACCESS,
                ).jti
            )
            issued_jtis.add(
                tokens.decode(
                    refresh_token,
                    expected_type=TokenType.REFRESH,
                ).jti
            )
            headers = {"Authorization": f"Bearer {access_token}"}
            print("tts_login: PASS (status=200)")

            unauthorized = await client.post(
                "/api/v1/audio/tts",
                json={"text": "未登录语音测试。"},
            )
            require_status(unauthorized, 401, "unauthorized TTS")
            print("tts_authentication: PASS (anonymous=401)")

            invalid = await client.post(
                "/api/v1/audio/tts",
                headers=headers,
                json={"text": "字段校验测试。", "voice": "forbidden-marker"},
            )
            require_status(invalid, 422, "internal field rejection")
            if "forbidden-marker" in invalid.text:
                raise AssertionError("Rejected internal field value leaked in response.")
            print("tts_strict_schema: PASS (extra_field=422)")

            response = await client.post(
                "/api/v1/audio/tts",
                headers=headers,
                json={"text": "您好，语音合成功能已经通过真实链路验证。"},
            )
            require_status(response, 200, "authenticated TTS")
            audio_format = validate_audio(
                response,
                settings.dify_tts_max_response_bytes,
            )
            if response.headers.get("cache-control") != "no-store":
                raise AssertionError("TTS response is missing no-store.")
            if response.headers.get("pragma") != "no-cache":
                raise AssertionError("TTS response is missing no-cache.")
            if response.headers.get("x-content-type-options") != "nosniff":
                raise AssertionError("TTS response is missing nosniff.")
            print(
                "tts_synthesis: PASS "
                f"(status=200, format={audio_format}, bytes_positive=true)"
            )

            logout = await client.post(
                "/api/v1/auth/logout",
                headers=headers,
                json={"refresh_token": refresh_token},
            )
            require_status(logout, 204, "logout")
            print("tts_logout: PASS (status=204)")
    finally:
        redis_keys = {f"auth:revoked:{jti}" for jti in issued_jtis}
        for key in redis_keys:
            await redis.delete(key)

        async with database.session_factory() as session:
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Role).where(Role.tenant_id == tenant_id))
            await session.commit()

        user_count, role_count = await fixture_counts(database, tenant_id)
        redis_count = 0
        for key in redis_keys:
            redis_count += int(await redis.exists(key))
        await redis.aclose()
        await database.close()
        print(
            "tts_temporary_fixtures: "
            f"users={user_count}, roles={role_count}, redis_keys={redis_count}"
        )
        if user_count or role_count or redis_count:
            raise AssertionError("Temporary TTS smoke fixtures were not fully removed.")


if __name__ == "__main__":
    run_async(verify())
