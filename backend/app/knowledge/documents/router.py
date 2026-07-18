from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.auth.dependencies import require_any_role
from app.auth.principal import Principal
from app.knowledge.documents.dependencies import get_knowledge_documents_service
from app.knowledge.documents.schemas import (
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOperationResponse,
    KnowledgeDocumentResponse,
    KnowledgeSyncJobResponse,
)
from app.knowledge.documents.service import KnowledgeDocumentsService

router = APIRouter(prefix="/knowledge", tags=["knowledge-documents"])
AdminPrincipal = Annotated[Principal, Depends(require_any_role("admin"))]
KnowledgeDocumentsServiceDependency = Annotated[
    KnowledgeDocumentsService,
    Depends(get_knowledge_documents_service),
]


@router.post(
    "/documents",
    response_model=KnowledgeDocumentOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传并索引知识文档",
)
async def upload_document(
    principal: AdminPrincipal,
    service: KnowledgeDocumentsServiceDependency,
    file: Annotated[UploadFile, File(description="PDF、DOCX 或 UTF-8 TXT")],
) -> KnowledgeDocumentOperationResponse:
    return await service.upload(principal, file)


@router.get(
    "/documents",
    response_model=KnowledgeDocumentListResponse,
    summary="查询知识文档台账",
)
async def list_documents(
    principal: AdminPrincipal,
    service: KnowledgeDocumentsServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeDocumentListResponse:
    return await service.list_documents(
        principal,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
    summary="查询知识文档详情",
)
async def get_document(
    document_id: UUID,
    principal: AdminPrincipal,
    service: KnowledgeDocumentsServiceDependency,
) -> KnowledgeDocumentResponse:
    return await service.get_document(principal, document_id)


@router.post(
    "/documents/{document_id}/reindex",
    response_model=KnowledgeDocumentOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重新索引知识文档",
)
async def reindex_document(
    document_id: UUID,
    principal: AdminPrincipal,
    service: KnowledgeDocumentsServiceDependency,
) -> KnowledgeDocumentOperationResponse:
    return await service.reindex(principal, document_id)


@router.delete(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="删除知识文档",
)
async def delete_document(
    document_id: UUID,
    principal: AdminPrincipal,
    service: KnowledgeDocumentsServiceDependency,
) -> KnowledgeDocumentOperationResponse:
    return await service.delete(principal, document_id)


@router.get(
    "/jobs/{job_id}",
    response_model=KnowledgeSyncJobResponse,
    summary="查询知识文档索引任务",
)
async def get_job(
    job_id: UUID,
    principal: AdminPrincipal,
    service: KnowledgeDocumentsServiceDependency,
) -> KnowledgeSyncJobResponse:
    return await service.get_job(principal, job_id)
