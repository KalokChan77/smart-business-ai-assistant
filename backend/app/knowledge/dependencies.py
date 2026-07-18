from typing import Annotated

from fastapi import Depends, Request

from app.ai.dify.factory import DifyDatasetClientFactory
from app.ai.dify.retriever import DifyDatasetRetriever
from app.knowledge.documents.visibility import KnowledgeDocumentVisibilityPolicy
from app.knowledge.service import KnowledgeService


def get_dify_dataset_client_factory(request: Request) -> DifyDatasetClientFactory:
    settings = request.app.state.settings
    return DifyDatasetClientFactory(
        base_url=settings.dify_base_url,
        api_key=(
            settings.dify_dataset_api_key.get_secret_value().strip()
            if settings.dify_dataset_api_key is not None
            else ""
        ),
        dataset_id=(settings.dify_dataset_id or "").strip(),
        timeout_seconds=settings.ai_request_timeout_seconds,
    )


def get_dify_dataset_retriever(
    factory: Annotated[
        DifyDatasetClientFactory,
        Depends(get_dify_dataset_client_factory),
    ],
) -> DifyDatasetRetriever:
    return DifyDatasetRetriever(factory)


def get_knowledge_service(
    request: Request,
    retriever: Annotated[
        DifyDatasetRetriever,
        Depends(get_dify_dataset_retriever),
    ],
) -> KnowledgeService:
    runtime = request.app.state.runtime
    database = runtime.database if runtime is not None else None
    return KnowledgeService(
        retriever=retriever,
        visibility=KnowledgeDocumentVisibilityPolicy(database),
    )
