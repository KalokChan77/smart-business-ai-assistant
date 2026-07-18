from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SynthesizedAudio:
    content: bytes
    media_type: str


class TextToSpeechGateway(Protocol):
    async def synthesize(
        self,
        *,
        text: str,
        user: str,
    ) -> SynthesizedAudio: ...


class TextToSpeechGatewayProvider(Protocol):
    def open(
        self,
    ) -> AbstractAsyncContextManager[TextToSpeechGateway]: ...
