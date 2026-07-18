from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChatInputMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatChunk:
    delta: str = ""
    finish_reason: str | None = None
    provider_request_id: str | None = None
    usage: TokenUsage | None = None


class ProviderError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ChatProvider(Protocol):
    name: str
    model: str

    def stream(
        self,
        messages: Sequence[ChatInputMessage],
    ) -> AsyncIterator[ChatChunk]: ...
