from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.ai.schemas import ProviderName


class AgentStreamRequest(BaseModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=100_000)
    provider: ProviderName | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message must not be empty.")
        return normalized
