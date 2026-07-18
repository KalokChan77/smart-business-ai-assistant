from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.customer_service.adapters import KnowledgeServiceAdapter
from app.customer_service.classification import RuleBasedTicketClassifier
from app.customer_service.repository import CustomerServiceRepository
from app.customer_service.service import CustomerService
from app.customer_service.workflow import CustomerServiceWorkflow
from app.db.dependencies import get_db_session
from app.knowledge.dependencies import get_knowledge_service
from app.knowledge.service import KnowledgeService

_classifier = RuleBasedTicketClassifier()


def get_customer_service_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomerServiceRepository:
    return CustomerServiceRepository(session)


def get_customer_service_classifier() -> RuleBasedTicketClassifier:
    return _classifier


def get_customer_service_workflow(
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    classifier: Annotated[
        RuleBasedTicketClassifier,
        Depends(get_customer_service_classifier),
    ],
) -> CustomerServiceWorkflow:
    return CustomerServiceWorkflow(
        classifier=classifier,
        knowledge=KnowledgeServiceAdapter(knowledge_service),
    )


def get_customer_service(
    repository: Annotated[
        CustomerServiceRepository,
        Depends(get_customer_service_repository),
    ],
    classifier: Annotated[
        RuleBasedTicketClassifier,
        Depends(get_customer_service_classifier),
    ],
    workflow: Annotated[
        CustomerServiceWorkflow,
        Depends(get_customer_service_workflow),
    ],
) -> CustomerService:
    return CustomerService(
        repository=repository,
        classifier=classifier,
        workflow=workflow,
    )
