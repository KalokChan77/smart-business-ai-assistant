from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

KnowledgeQueryOutcome = Literal["answered", "no_match", "refused"]


class KnowledgeQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10_000)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeCitation(BaseModel):
    rank: int = Field(ge=1)
    document_name: str
    excerpt: str
    score: float | None = None


class KnowledgeQueryResponse(BaseModel):
    outcome: KnowledgeQueryOutcome
    answer: str
    citations: list[KnowledgeCitation]
    retrieval_count: int = Field(ge=0)
