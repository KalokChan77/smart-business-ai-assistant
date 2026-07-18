from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.knowledge.dependencies import get_knowledge_service
from app.knowledge.schemas import KnowledgeQueryRequest, KnowledgeQueryResponse
from app.knowledge.service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
KnowledgeServiceDependency = Annotated[
    KnowledgeService,
    Depends(get_knowledge_service),
]


@router.post(
    "/query",
    response_model=KnowledgeQueryResponse,
    summary="查询企业知识库并返回引用",
)
async def query_knowledge(
    payload: KnowledgeQueryRequest,
    principal: CurrentPrincipal,
    service: KnowledgeServiceDependency,
) -> KnowledgeQueryResponse:
    return await service.query(principal, payload)

