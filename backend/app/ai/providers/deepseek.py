import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.ai.providers.base import (
    ChatChunk,
    ChatInputMessage,
    ProviderError,
    TokenUsage,
)


class DeepSeekProvider:
    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport
        self._timeout = httpx.Timeout(
            connect=min(timeout_seconds, 15.0),
            read=timeout_seconds,
            write=min(timeout_seconds, 30.0),
            pool=min(timeout_seconds, 15.0),
        )

    async def stream(
        self,
        messages: Sequence[ChatInputMessage],
    ) -> AsyncIterator[ChatChunk]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": item.role, "content": item.content} for item in messages
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code != httpx.codes.OK:
                        raise self._http_error(response.status_code)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        yield self._parse_chunk(data)
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError(
                code="ai_provider_timeout",
                message="模型服务响应超时。",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                code="ai_provider_unavailable",
                message="模型服务暂时不可用。",
            ) from exc

    @staticmethod
    def _http_error(status_code: int) -> ProviderError:
        if status_code in {401, 403}:
            return ProviderError(
                code="ai_provider_authentication_failed",
                message="模型服务认证失败。",
            )
        if status_code == 429:
            return ProviderError(
                code="ai_provider_rate_limited",
                message="模型服务请求过于频繁。",
            )
        return ProviderError(
            code="ai_provider_unavailable",
            message="模型服务暂时不可用。",
        )

    @staticmethod
    def _parse_chunk(data: str) -> ChatChunk:
        try:
            payload = json.loads(data)
            choices = payload.get("choices") or []
            choice = choices[0] if choices else {}
            delta = choice.get("delta") or {}
            content = delta.get("content") or ""
            usage_data = payload.get("usage") or None
            usage = None
            if usage_data is not None:
                usage = TokenUsage(
                    input_tokens=usage_data.get("prompt_tokens"),
                    output_tokens=usage_data.get("completion_tokens"),
                )
            return ChatChunk(
                delta=content,
                finish_reason=choice.get("finish_reason"),
                provider_request_id=payload.get("id"),
                usage=usage,
            )
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(
                code="ai_provider_protocol_error",
                message="模型服务返回了无法解析的数据。",
            ) from exc
