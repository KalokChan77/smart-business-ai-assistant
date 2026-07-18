from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.ai.models import AIRun, AIRunMode, AIRunStatus

ProviderName = Literal["deepseek", "dashscope"]


class ChatStreamRequest(BaseModel):
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


class AIRunResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    request_id: str
    provider: str
    model: str
    mode: AIRunMode
    status: AIRunStatus
    prompt_message_id: UUID | None
    response_message_id: UUID | None
    input_tokens: int | None
    output_tokens: int | None
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, run: AIRun) -> "AIRunResponse":
        return cls(
            id=run.id,
            conversation_id=run.conversation_id,
            request_id=run.request_id,
            provider=run.provider,
            model=run.model,
            mode=run.mode,
            status=run.status,
            prompt_message_id=run.prompt_message_id,
            response_message_id=run.response_message_id,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            error_code=run.error_code,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
