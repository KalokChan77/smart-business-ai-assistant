from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dify.factory import DifyDatasetClientFactory
from app.db.dependencies import get_db_session
from app.knowledge.dependencies import get_dify_dataset_client_factory
from app.knowledge.documents.repository import KnowledgeDocumentsRepository
from app.knowledge.documents.service import KnowledgeDocumentsService
from app.knowledge.documents.storage import KnowledgeFileStorage
from app.knowledge.documents.validation import KnowledgeFileValidator


def get_knowledge_documents_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeDocumentsRepository:
    return KnowledgeDocumentsRepository(session)


def get_knowledge_file_validator(request: Request) -> KnowledgeFileValidator:
    return KnowledgeFileValidator(
        max_bytes=request.app.state.settings.knowledge_max_upload_bytes,
    )


def get_knowledge_file_storage(request: Request) -> KnowledgeFileStorage:
    return KnowledgeFileStorage(request.app.state.settings.knowledge_upload_dir)


def get_knowledge_documents_service(
    repository: Annotated[
        KnowledgeDocumentsRepository,
        Depends(get_knowledge_documents_repository),
    ],
    validator: Annotated[
        KnowledgeFileValidator,
        Depends(get_knowledge_file_validator),
    ],
    storage: Annotated[
        KnowledgeFileStorage,
        Depends(get_knowledge_file_storage),
    ],
    dify_factory: Annotated[
        DifyDatasetClientFactory,
        Depends(get_dify_dataset_client_factory),
    ],
) -> KnowledgeDocumentsService:
    return KnowledgeDocumentsService(
        repository=repository,
        validator=validator,
        storage=storage,
        dify_factory=dify_factory,
    )
