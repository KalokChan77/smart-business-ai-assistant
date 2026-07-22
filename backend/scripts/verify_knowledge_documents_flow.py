"""Run a disposable authenticated knowledge-document lifecycle smoke test."""

import asyncio
import os
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select

from app.ai.dify.exceptions import DifyClientError, DifyNotFoundError
from app.ai.dify.factory import DifyDatasetClientFactory
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.core.asyncio_compat import run_async
from app.core.config import Settings
from app.db.session import Database
from app.knowledge.documents.models import KnowledgeDocument, KnowledgeSyncJob
from app.knowledge.documents.storage import KnowledgeFileStorage, KnowledgeStorageError
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.service import UserService

_FORBIDDEN_RESPONSE_FIELDS = {
    "api_key",
    "batch",
    "dataset_id",
    "dify_batch_id",
    "dify_document_id",
    "retrieval_model",
    "sha256",
    "storage_key",
}


def require_secret(value, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"{name} must be configured.")
    return value.get_secret_value().strip()


def require_status(response: httpx.Response, expected: int, operation: str) -> None:
    if response.status_code != expected:
        raise AssertionError(
            f"{operation} failed with HTTP {response.status_code}."
        )


def response_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for nested in value.values():
            keys.update(response_keys(nested))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for nested in value:
            keys.update(response_keys(nested))
        return keys
    return set()


def assert_safe_response(
    response: httpx.Response,
    protected_values: tuple[str, ...],
) -> object:
    if any(value and value in response.text for value in protected_values):
        raise AssertionError("A protected server value appeared in a response.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError("Platform API returned non-JSON content.") from exc
    leaked_fields = _FORBIDDEN_RESPONSE_FIELDS.intersection(response_keys(payload))
    if leaked_fields:
        raise AssertionError("A protected internal field appeared in a response.")
    return payload


async def poll_job(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    job_id: str,
    protected_values: tuple[str, ...],
) -> dict:
    for _ in range(120):
        response = await client.get(
            f"/api/v1/knowledge/jobs/{job_id}",
            headers=headers,
        )
        require_status(response, 200, "knowledge job polling")
        payload = assert_safe_response(response, protected_values)
        if not isinstance(payload, dict):
            raise AssertionError("Knowledge job response is invalid.")
        job_status = payload.get("status")
        if job_status == "completed":
            return payload
        if job_status == "failed":
            raise AssertionError("Knowledge document indexing failed.")
        if job_status not in {"pending", "processing"}:
            raise AssertionError("Knowledge job returned an unknown status.")
        await asyncio.sleep(1)
    raise AssertionError("Knowledge document indexing did not finish in time.")


async def fixture_counts(
    database: Database,
    tenant_ids: tuple[UUID, ...],
) -> tuple[int, int, int, int]:
    async with database.session_factory() as session:
        document_count = await session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.tenant_id.in_(tenant_ids))
        )
        job_count = await session.scalar(
            select(func.count())
            .select_from(KnowledgeSyncJob)
            .where(KnowledgeSyncJob.tenant_id.in_(tenant_ids))
        )
        user_count = await session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id.in_(tenant_ids))
        )
        role_count = await session.scalar(
            select(func.count()).select_from(Role).where(Role.tenant_id.in_(tenant_ids))
        )
    return (
        int(document_count or 0),
        int(job_count or 0),
        int(user_count or 0),
        int(role_count or 0),
    )


async def cleanup_documents(
    *,
    database: Database,
    storage: KnowledgeFileStorage,
    dify_factory: DifyDatasetClientFactory,
    tenant_ids: tuple[UUID, ...],
) -> int:
    async with database.session_factory() as session:
        documents = list(
            (
                await session.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.tenant_id.in_(tenant_ids)
                    )
                )
            ).all()
        )

    cleanup_failures = 0
    for document in documents:
        if document.dify_document_id:
            try:
                async with dify_factory.open() as client:
                    await client.delete_document(
                        document_id=document.dify_document_id,
                    )
            except DifyNotFoundError:
                pass
            except DifyClientError:
                cleanup_failures += 1
        try:
            await storage.delete(document.storage_key)
        except KnowledgeStorageError:
            cleanup_failures += 1

    async with database.session_factory() as session:
        await session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id.in_(tenant_ids)
            )
        )
        await session.commit()
    return cleanup_failures


async def verify() -> None:
    settings = Settings()
    database_url = require_secret(settings.database_url, "DATABASE_URL")
    redis_url = require_secret(settings.redis_url, "REDIS_URL")
    jwt_secret = require_secret(settings.jwt_secret_key, "JWT_SECRET_KEY")
    dataset_key = require_secret(
        settings.dify_dataset_api_key,
        "DIFY_DATASET_API_KEY",
    )
    protected_values = tuple(
        value
        for value in (
            database_url,
            redis_url,
            jwt_secret,
            dataset_key,
            require_secret(settings.dify_chat_app_api_key, "DIFY_CHAT_APP_API_KEY"),
            require_secret(settings.dify_workflow_api_key, "DIFY_WORKFLOW_API_KEY"),
        )
        if value
    )
    dataset_id = (settings.dify_dataset_id or "").strip()
    if not dataset_id:
        raise RuntimeError("DIFY_DATASET_ID must be configured.")

    database = Database.create(database_url)
    redis = create_redis_client(redis_url)
    storage = KnowledgeFileStorage(settings.knowledge_upload_dir)
    dify_factory = DifyDatasetClientFactory(
        base_url=settings.dify_base_url,
        api_key=dataset_key,
        dataset_id=dataset_id,
        timeout_seconds=settings.ai_request_timeout_seconds,
    )
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
    outsider_password = secrets.token_urlsafe(24)
    issued_tokens: list[tuple[str, TokenType]] = []
    redis_keys: set[str] = set()
    cleanup_failures = 0

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin = await users.bootstrap_admin(
                tenant_id=tenant_id,
                username=f"knowledge-document-smoke-{suffix}",
                email=f"knowledge-document-smoke-{suffix}@example.test",
                password=password,
            )
            outsider_admin = await users.bootstrap_admin(
                tenant_id=outsider_tenant_id,
                username=f"knowledge-document-outsider-{suffix}",
                email=f"knowledge-document-outsider-{suffix}@example.test",
                password=outsider_password,
            )

        base_url = os.getenv(
            "KNOWLEDGE_DOCUMENT_SMOKE_BASE_URL",
            "http://127.0.0.1:8000",
        )
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
            require_status(login, 200, "login")
            pair = assert_safe_response(login, protected_values)
            if not isinstance(pair, dict):
                raise AssertionError("Login response is invalid.")
            issued_tokens.extend(
                [
                    (str(pair["access_token"]), TokenType.ACCESS),
                    (str(pair["refresh_token"]), TokenType.REFRESH),
                ]
            )
            headers = {"Authorization": f"Bearer {pair['access_token']}"}

            outsider_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_id": str(outsider_tenant_id),
                    "username": outsider_admin.username,
                    "password": outsider_password,
                },
            )
            require_status(outsider_login, 200, "outsider login")
            outsider_pair = assert_safe_response(outsider_login, protected_values)
            if not isinstance(outsider_pair, dict):
                raise AssertionError("Outsider login response is invalid.")
            issued_tokens.extend(
                [
                    (str(outsider_pair["access_token"]), TokenType.ACCESS),
                    (str(outsider_pair["refresh_token"]), TokenType.REFRESH),
                ]
            )
            outsider_headers = {
                "Authorization": f"Bearer {outsider_pair['access_token']}"
            }

            filename = f"knowledge-document-smoke-{suffix}.txt"
            content = (
                "教学冒烟专项条款。"
                "玄曜苍麟校验码为 QZKX-7931，"
                "仅用于验证上传、索引、重建和删除闭环。"
            ).encode()
            uploaded = await client.post(
                "/api/v1/knowledge/documents",
                headers=headers,
                files={"file": (filename, content, "text/plain")},
            )
            require_status(uploaded, 202, "knowledge document upload")
            upload_payload = assert_safe_response(uploaded, protected_values)
            if not isinstance(upload_payload, dict):
                raise AssertionError("Upload response is invalid.")
            document = upload_payload.get("document")
            job = upload_payload.get("job")
            if not isinstance(document, dict) or not isinstance(job, dict):
                raise AssertionError("Upload response is missing document or job.")
            document_id = str(document.get("id") or "")
            upload_job_id = str(job.get("id") or "")
            if not document_id or not upload_job_id:
                raise AssertionError("Upload response is missing local identifiers.")
            print("document_upload: PASS (status=202, state=accepted)")

            await poll_job(
                client,
                headers=headers,
                job_id=upload_job_id,
                protected_values=protected_values,
            )
            print("document_indexing: PASS (state=completed)")

            detailed = await client.get(
                f"/api/v1/knowledge/documents/{document_id}",
                headers=headers,
            )
            require_status(detailed, 200, "knowledge document detail")
            detail_payload = assert_safe_response(detailed, protected_values)
            if not isinstance(detail_payload, dict) or detail_payload.get("status") != "completed":
                raise AssertionError("Knowledge document detail is not completed.")

            outsider_query = await client.post(
                "/api/v1/knowledge/query",
                headers=outsider_headers,
                json={"query": "玄曜苍麟校验码是什么？"},
            )
            require_status(
                outsider_query,
                200,
                "cross-tenant knowledge query",
            )
            outsider_query_payload = assert_safe_response(
                outsider_query,
                protected_values,
            )
            if (
                not isinstance(outsider_query_payload, dict)
                or outsider_query_payload.get("outcome") != "no_match"
                or outsider_query_payload.get("citations")
            ):
                raise AssertionError("Managed document crossed the tenant boundary.")
            print("document_tenant_isolation: PASS (outsider=no_match)")

            owner_query = await client.post(
                "/api/v1/knowledge/query",
                headers=headers,
                json={"query": "玄曜苍麟校验码是什么？"},
            )
            require_status(owner_query, 200, "knowledge query after upload")
            owner_query_payload = assert_safe_response(
                owner_query,
                protected_values,
            )
            if (
                not isinstance(owner_query_payload, dict)
                or owner_query_payload.get("outcome") != "answered"
                or not owner_query_payload.get("citations")
            ):
                raise AssertionError("Uploaded document was not retrievable by its owner.")
            print("document_retrieval: PASS (owner=answered)")

            reindexed = await client.post(
                f"/api/v1/knowledge/documents/{document_id}/reindex",
                headers=headers,
            )
            require_status(reindexed, 202, "knowledge document reindex")
            reindex_payload = assert_safe_response(reindexed, protected_values)
            if not isinstance(reindex_payload, dict):
                raise AssertionError("Reindex response is invalid.")
            reindex_job = reindex_payload.get("job")
            if not isinstance(reindex_job, dict) or reindex_job.get("operation") != "reindex":
                raise AssertionError("Reindex response operation is invalid.")
            reindex_job_id = str(reindex_job.get("id") or "")
            await poll_job(
                client,
                headers=headers,
                job_id=reindex_job_id,
                protected_values=protected_values,
            )
            print("document_reindex: PASS (state=completed)")

            deleted = await client.delete(
                f"/api/v1/knowledge/documents/{document_id}",
                headers=headers,
            )
            require_status(deleted, 202, "knowledge document delete")
            delete_payload = assert_safe_response(deleted, protected_values)
            if not isinstance(delete_payload, dict):
                raise AssertionError("Delete response is invalid.")
            deleted_document = delete_payload.get("document")
            delete_job = delete_payload.get("job")
            if (
                not isinstance(deleted_document, dict)
                or deleted_document.get("status") != "deleted"
                or not isinstance(delete_job, dict)
                or delete_job.get("status") != "completed"
            ):
                raise AssertionError("Delete response did not reach completed state.")

            missing = await client.get(
                f"/api/v1/knowledge/documents/{document_id}",
                headers=headers,
            )
            require_status(missing, 404, "deleted knowledge document detail")
            assert_safe_response(missing, protected_values)
            print("document_delete: PASS (local=deleted, upstream=deleted)")

            logout = await client.post(
                "/api/v1/auth/logout",
                headers=headers,
                json={"refresh_token": pair["refresh_token"]},
            )
            require_status(logout, 204, "logout")
            outsider_logout = await client.post(
                "/api/v1/auth/logout",
                headers=outsider_headers,
                json={"refresh_token": outsider_pair["refresh_token"]},
            )
            require_status(outsider_logout, 204, "outsider logout")
    finally:
        cleanup_failures += await cleanup_documents(
            database=database,
            storage=storage,
            dify_factory=dify_factory,
            tenant_ids=tenant_ids,
        )

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

        document_count, job_count, user_count, role_count = await fixture_counts(
            database,
            tenant_ids,
        )
        redis_count = 0
        for key in redis_keys:
            redis_count += int(await redis.exists(key))
        await redis.aclose()
        await database.close()
        if any(
            (
                cleanup_failures,
                document_count,
                job_count,
                user_count,
                role_count,
                redis_count,
            )
        ):
            raise AssertionError(
                "Temporary knowledge document smoke fixtures were not fully cleaned."
            )
        print(
            "temporary document smoke fixtures: "
            "documents=0, jobs=0, users=0, roles=0, redis_keys=0"
        )


if __name__ == "__main__":
    run_async(verify())
