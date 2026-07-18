from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import AppError
from app.knowledge.documents.dependencies import get_knowledge_documents_service
from app.knowledge.documents.models import (
    KnowledgeDocumentStatus,
    KnowledgeSyncJobStatus,
    KnowledgeSyncOperation,
)
from app.knowledge.documents.schemas import (
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOperationResponse,
    KnowledgeDocumentResponse,
    KnowledgeSyncJobResponse,
)
from app.main import create_app


class RoleAwareAuthenticationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate_access_token(self, access_token: str) -> Principal:
        if access_token != "access-token":
            raise AppError(code="invalid_token", message="令牌无效。", status_code=401)
        return self.principal


class FakeKnowledgeDocumentsService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.document = KnowledgeDocumentResponse(
            id=uuid4(),
            filename="rules.txt",
            media_type="text/plain",
            extension="txt",
            size_bytes=12,
            status=KnowledgeDocumentStatus.PROCESSING,
            indexing_status="waiting",
            latest_error_code=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.job = KnowledgeSyncJobResponse(
            id=uuid4(),
            document_id=self.document.id,
            operation=KnowledgeSyncOperation.UPLOAD,
            status=KnowledgeSyncJobStatus.PROCESSING,
            indexing_status="waiting",
            completed_segments=0,
            total_segments=0,
            error_code=None,
            started_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.calls: list[tuple[str, object]] = []

    async def upload(self, principal: Principal, upload) -> KnowledgeDocumentOperationResponse:
        self.calls.append(("upload", (principal.tenant_id, upload.filename)))
        return KnowledgeDocumentOperationResponse(
            document=self.document,
            job=self.job,
        )

    async def list_documents(
        self,
        principal: Principal,
        *,
        limit: int,
        offset: int,
    ) -> KnowledgeDocumentListResponse:
        self.calls.append(("list", (principal.tenant_id, limit, offset)))
        return KnowledgeDocumentListResponse(
            items=[self.document],
            total=1,
            limit=limit,
            offset=offset,
        )

    async def get_document(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocumentResponse:
        self.calls.append(("detail", (principal.tenant_id, document_id)))
        return self.document

    async def reindex(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocumentOperationResponse:
        self.calls.append(("reindex", (principal.tenant_id, document_id)))
        return KnowledgeDocumentOperationResponse(
            document=self.document,
            job=self.job.model_copy(update={"operation": KnowledgeSyncOperation.REINDEX}),
        )

    async def delete(
        self,
        principal: Principal,
        document_id: UUID,
    ) -> KnowledgeDocumentOperationResponse:
        self.calls.append(("delete", (principal.tenant_id, document_id)))
        return KnowledgeDocumentOperationResponse(
            document=self.document.model_copy(
                update={"status": KnowledgeDocumentStatus.DELETED}
            ),
            job=self.job.model_copy(
                update={
                    "operation": KnowledgeSyncOperation.DELETE,
                    "status": KnowledgeSyncJobStatus.COMPLETED,
                }
            ),
        )

    async def get_job(
        self,
        principal: Principal,
        job_id: UUID,
    ) -> KnowledgeSyncJobResponse:
        self.calls.append(("job", (principal.tenant_id, job_id)))
        return self.job


def make_app(role: str):
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="current",
        email="current@example.test",
        roles=frozenset({role}),
    )
    auth = RoleAwareAuthenticationService(principal)
    service = FakeKnowledgeDocumentsService()
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_knowledge_documents_service] = lambda: service
    return app, principal, service


async def test_admin_can_use_complete_knowledge_document_api_contract() -> None:
    app, principal, service = make_app("admin")
    headers = {"Authorization": "Bearer access-token"}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        uploaded = await client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            files={"file": ("rules.txt", b"teaching rules", "text/plain")},
        )
        listed = await client.get(
            "/api/v1/knowledge/documents?limit=10&offset=2",
            headers=headers,
        )
        detailed = await client.get(
            f"/api/v1/knowledge/documents/{service.document.id}",
            headers=headers,
        )
        reindexed = await client.post(
            f"/api/v1/knowledge/documents/{service.document.id}/reindex",
            headers=headers,
        )
        deleted = await client.delete(
            f"/api/v1/knowledge/documents/{service.document.id}",
            headers=headers,
        )
        job = await client.get(
            f"/api/v1/knowledge/jobs/{service.job.id}",
            headers=headers,
        )

    assert uploaded.status_code == 202
    assert uploaded.json()["document"]["filename"] == "rules.txt"
    assert uploaded.json()["job"]["operation"] == "upload"
    assert listed.status_code == 200
    assert listed.json()["limit"] == 10
    assert listed.json()["offset"] == 2
    assert detailed.status_code == 200
    assert reindexed.status_code == 202
    assert reindexed.json()["job"]["operation"] == "reindex"
    assert deleted.status_code == 202
    assert deleted.json()["document"]["status"] == "deleted"
    assert job.status_code == 200
    assert service.calls == [
        ("upload", (principal.tenant_id, "rules.txt")),
        ("list", (principal.tenant_id, 10, 2)),
        ("detail", (principal.tenant_id, service.document.id)),
        ("reindex", (principal.tenant_id, service.document.id)),
        ("delete", (principal.tenant_id, service.document.id)),
        ("job", (principal.tenant_id, service.job.id)),
    ]

    serialized = " ".join(
        response.text
        for response in (uploaded, listed, detailed, reindexed, deleted, job)
    )
    for forbidden in (
        "storage_key",
        "sha256",
        "dataset_id",
        "dify_document_id",
        "dify_batch_id",
        "api_key",
    ):
        assert forbidden not in serialized.lower()


async def test_non_admin_cannot_access_any_knowledge_document_endpoint() -> None:
    app, _, service = make_app("user")
    headers = {"Authorization": "Bearer access-token"}
    requests = (
        ("GET", "/api/v1/knowledge/documents", None),
        ("GET", f"/api/v1/knowledge/documents/{service.document.id}", None),
        (
            "POST",
            f"/api/v1/knowledge/documents/{service.document.id}/reindex",
            None,
        ),
        ("DELETE", f"/api/v1/knowledge/documents/{service.document.id}", None),
        ("GET", f"/api/v1/knowledge/jobs/{service.job.id}", None),
        (
            "POST",
            "/api/v1/knowledge/documents",
            {"file": ("rules.txt", b"rules", "text/plain")},
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = []
        for method, path, files in requests:
            responses.append(
                await client.request(method, path, headers=headers, files=files)
            )

    assert all(response.status_code == 403 for response in responses)
    assert all(response.json()["error"]["code"] == "forbidden" for response in responses)
    assert service.calls == []


async def test_document_paths_use_unified_validation_error_contract() -> None:
    app, _, _ = make_app("admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/knowledge/documents/not-a-uuid",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
