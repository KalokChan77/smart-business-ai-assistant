from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.ai.dify.exceptions import DifyConfigurationError
from app.audio.client import DifyTextToSpeechClient

_MAX_TTS_RESPONSE_BYTES = 5 * 1024 * 1024


class DifyTextToSpeechClientFactory:
    """Validate TTS connection settings and open short-lived HTTP clients."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    @asynccontextmanager
    async def open(self) -> AsyncIterator[DifyTextToSpeechClient]:
        base_url, api_key = self._validated_configuration()
        async with httpx.AsyncClient(
            base_url=f"{base_url}/",
            timeout=self._timeout_seconds,
            trust_env=False,
        ) as http_client:
            yield DifyTextToSpeechClient(
                http_client=http_client,
                api_key=api_key,
                max_response_bytes=self._max_response_bytes,
            )

    def _validated_configuration(self) -> tuple[str, str]:
        base_url = self._base_url.strip().rstrip("/")
        api_key = self._api_key.strip()
        if not base_url:
            raise DifyConfigurationError("Dify base URL is not configured.")
        try:
            parsed_url = httpx.URL(base_url)
        except Exception as exc:
            raise DifyConfigurationError("Dify base URL is invalid.") from exc
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.host
            or parsed_url.userinfo
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise DifyConfigurationError("Dify base URL is invalid.")
        if not api_key:
            raise DifyConfigurationError("Dify TTS is not configured.")
        if self._timeout_seconds <= 0:
            raise DifyConfigurationError("Dify timeout is invalid.")
        if not 0 < self._max_response_bytes <= _MAX_TTS_RESPONSE_BYTES:
            raise DifyConfigurationError("Dify audio size limit is invalid.")
        return base_url, api_key
