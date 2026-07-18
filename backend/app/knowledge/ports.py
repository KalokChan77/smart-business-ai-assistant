from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    document_id: str
    document_name: str
    content: str
    score: float | None


class KnowledgeRetriever(Protocol):
    async def retrieve(self, query: str) -> tuple[KnowledgeRecord, ...]: ...


class KnowledgeVisibilityPolicy(Protocol):
    async def filter_visible(
        self,
        tenant_id: UUID,
        records: tuple[KnowledgeRecord, ...],
    ) -> tuple[KnowledgeRecord, ...]: ...
