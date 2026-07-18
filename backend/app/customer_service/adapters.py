from app.auth.principal import Principal
from app.customer_service.models import CustomerServiceKnowledgeOutcome
from app.customer_service.ports import (
    CustomerServiceCitation,
    CustomerServiceKnowledgeResult,
)
from app.knowledge.schemas import KnowledgeQueryRequest
from app.knowledge.service import KnowledgeService


class KnowledgeServiceAdapter:
    def __init__(self, service: KnowledgeService) -> None:
        self._service = service

    async def answer(
        self,
        principal: Principal,
        query: str,
    ) -> CustomerServiceKnowledgeResult:
        response = await self._service.query(
            principal,
            KnowledgeQueryRequest(query=query),
        )
        return CustomerServiceKnowledgeResult(
            outcome=CustomerServiceKnowledgeOutcome(response.outcome),
            answer=response.answer,
            citations=tuple(
                CustomerServiceCitation(
                    rank=citation.rank,
                    document_name=citation.document_name,
                    excerpt=citation.excerpt,
                    score=citation.score,
                )
                for citation in response.citations
            ),
        )
