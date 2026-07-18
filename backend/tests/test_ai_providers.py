import json
from http import HTTPStatus
from types import SimpleNamespace

import httpx
import pytest

from app.ai.providers.base import ChatInputMessage, ProviderError
from app.ai.providers.dashscope import DashScopeProvider
from app.ai.providers.deepseek import DeepSeekProvider


async def test_deepseek_provider_parses_incremental_sse_and_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer ")
        payload = json.loads(request.content)
        assert payload["stream"] is True
        body = "\n".join(
            [
                'data: {"id":"req-1","choices":[{"delta":{"content":"你"},"finish_reason":null}]}',
                '',
                'data: {"id":"req-1","choices":[{"delta":{"content":"好"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
                '',
                'data: [DONE]',
                '',
            ]
        )
        return httpx.Response(200, text=body)

    provider = DeepSeekProvider(
        api_key="test-key",
        base_url="https://example.test",
        model="deepseek-chat",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )
    chunks = [
        chunk
        async for chunk in provider.stream(
            [ChatInputMessage(role="user", content="你好")]
        )
    ]

    assert "".join(chunk.delta for chunk in chunks) == "你好"
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.input_tokens == 3
    assert chunks[-1].usage.output_tokens == 2


async def test_deepseek_provider_maps_rate_limit_without_leaking_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="sensitive upstream detail")

    provider = DeepSeekProvider(
        api_key="test-key",
        base_url="https://example.test",
        model="deepseek-chat",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as captured:
        _ = [
            chunk
            async for chunk in provider.stream(
                [ChatInputMessage(role="user", content="hello")]
            )
        ]
    assert captured.value.code == "ai_provider_rate_limited"
    assert "sensitive" not in captured.value.message


async def test_dashscope_provider_parses_incremental_stream(monkeypatch) -> None:
    async def response_stream():
        yield SimpleNamespace(
            status_code=HTTPStatus.OK,
            request_id="dash-1",
            output=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="你"),
                        finish_reason=None,
                    )
                ]
            ),
            usage=SimpleNamespace(input_tokens=4, output_tokens=1),
        )
        yield SimpleNamespace(
            status_code=HTTPStatus.OK,
            request_id="dash-1",
            output=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="好"),
                        finish_reason="stop",
                    )
                ]
            ),
            usage=SimpleNamespace(input_tokens=4, output_tokens=2),
        )

    async def fake_call(**kwargs):
        assert kwargs["stream"] is True
        assert kwargs["incremental_output"] is True
        assert kwargs["base_address"] == "https://example.test/api/v1"
        return response_stream()

    monkeypatch.setattr("app.ai.providers.dashscope.AioGeneration.call", fake_call)
    provider = DashScopeProvider(
        api_key="test-key",
        base_url="https://example.test/api/v1",
        model="qwen-plus",
        workspace_id=None,
    )
    chunks = [
        chunk
        async for chunk in provider.stream(
            [ChatInputMessage(role="user", content="你好")]
        )
    ]

    assert "".join(chunk.delta for chunk in chunks) == "你好"
    assert chunks[-1].provider_request_id == "dash-1"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.output_tokens == 2
