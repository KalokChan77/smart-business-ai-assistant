from app.ai.dify.factory import DifyDatasetClientFactory
from app.knowledge.ports import KnowledgeRecord


class DifyDatasetRetriever:
    """Create the Dify HTTP client only when an actual retrieval is required."""

    def __init__(self, factory: DifyDatasetClientFactory) -> None:
        self._factory = factory

    async def retrieve(self, query: str) -> tuple[KnowledgeRecord, ...]:
        async with self._factory.open() as client:
            records = await client.retrieve(query)
        return tuple(
            KnowledgeRecord(
                document_id=record.document_id,
                document_name=record.document_name,
                content=record.content,
                score=record.score,
            )
            for record in records
        )
