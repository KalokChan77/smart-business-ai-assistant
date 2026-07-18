from collections.abc import AsyncIterator, Sequence
from http import HTTPStatus

from dashscope import AioGeneration

from app.ai.providers.base import (
    ChatChunk,
    ChatInputMessage,
    ProviderError,
    TokenUsage,
)


class DashScopeProvider:
    name = "dashscope"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        workspace_id: str | None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._workspace_id = workspace_id

    async def stream(
        self,
        messages: Sequence[ChatInputMessage],
    ) -> AsyncIterator[ChatChunk]:
        try:
            responses = await AioGeneration.call(
                model=self.model,
                api_key=self._api_key,
                workspace=self._workspace_id,
                base_address=self._base_url,
                messages=[
                    {"role": item.role, "content": item.content}
                    for item in messages
                ],
                result_format="message",
                stream=True,
                incremental_output=True,
            )
            if not hasattr(responses, "__aiter__"):
                raise ProviderError(
                    code="ai_provider_protocol_error",
                    message="模型服务未返回流式响应。",
                )
            async for response in responses:
                if response.status_code != HTTPStatus.OK:
                    raise self._response_error(response.status_code)
                choices = getattr(response.output, "choices", None) or []
                choice = choices[0] if choices else None
                message = getattr(choice, "message", None) if choice else None
                content = getattr(message, "content", "") if message else ""
                usage_data = getattr(response, "usage", None)
                usage = None
                if usage_data is not None:
                    usage = TokenUsage(
                        input_tokens=getattr(usage_data, "input_tokens", None),
                        output_tokens=getattr(usage_data, "output_tokens", None),
                    )
                yield ChatChunk(
                    delta=content if isinstance(content, str) else "",
                    finish_reason=getattr(choice, "finish_reason", None),
                    provider_request_id=getattr(response, "request_id", None),
                    usage=usage,
                )
        except ProviderError:
            raise
        except TimeoutError as exc:
            raise ProviderError(
                code="ai_provider_timeout",
                message="模型服务响应超时。",
            ) from exc
        except Exception as exc:
            raise ProviderError(
                code="ai_provider_unavailable",
                message="模型服务暂时不可用。",
            ) from exc

    @staticmethod
    def _response_error(status_code: int) -> ProviderError:
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
