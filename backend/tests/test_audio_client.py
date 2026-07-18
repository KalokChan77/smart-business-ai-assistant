import io
import json
import wave

import httpx
import pytest

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyNotFoundError,
    DifyProtocolError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.audio.client import DifyTextToSpeechClient


def make_wave_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 32)
    return output.getvalue()


def make_mp3_bytes(*, include_id3: bool = True) -> bytes:
    frame_header = b"\xff\xfb\x90\x00"
    frame_length = 417
    frame = frame_header + b"\x00" * (frame_length - len(frame_header))
    id3_header = b"ID3\x04\x00\x00\x00\x00\x00\x00" if include_id3 else b""
    return id3_header + frame


async def test_dify_tts_client_sends_minimal_request_and_normalizes_wave_type() -> None:
    wave_bytes = make_wave_bytes()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/text-to-audio"
        assert request.headers["Authorization"] == "Bearer chat-test-key"
        assert json.loads(request.content) == {
            "text": "退款申请已经进入审核流程。",
            "user": "stable-user-alias",
        }
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/mpeg"},
            content=wave_bytes,
        )

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=1024,
        )
        result = await client.synthesize(
            text="退款申请已经进入审核流程。",
            user="stable-user-alias",
        )

    assert result.content == wave_bytes
    assert result.media_type == "audio/wav"


async def test_dify_tts_client_accepts_mp3_signature() -> None:
    mp3_bytes = make_mp3_bytes()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/mpeg"},
            content=mp3_bytes,
        )

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=1024,
        )
        result = await client.synthesize(text="测试", user="user")

    assert result.content == mp3_bytes
    assert result.media_type == "audio/mpeg"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, DifyAuthenticationError),
        (403, DifyAuthenticationError),
        (404, DifyNotFoundError),
        (429, DifyRateLimitError),
        (400, DifyRejectedError),
        (500, DifyUnavailableError),
        (503, DifyUnavailableError),
    ],
)
async def test_dify_tts_client_maps_http_failures_without_response_body(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="sensitive upstream response")

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=1024,
        )
        with pytest.raises(expected_error) as captured:
            await client.synthesize(text="测试", user="user")

    assert "sensitive" not in str(captured.value)


async def test_dify_tts_client_maps_timeout_without_internal_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive timeout detail", request=request)

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=1024,
        )
        with pytest.raises(DifyTimeoutError) as captured:
            await client.synthesize(text="测试", user="user")

    assert "sensitive" not in str(captured.value)


async def test_dify_tts_client_maps_network_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=1024,
        )
        with pytest.raises(DifyUnavailableError):
            await client.synthesize(text="测试", user="user")


@pytest.mark.parametrize(
    ("headers", "content"),
    [
        ({"Content-Type": "application/json"}, b'{"audio":"fake"}'),
        ({"Content-Type": "audio/mpeg"}, b""),
        ({"Content-Type": "audio/mpeg"}, b"not-supported-audio"),
        ({"Content-Type": "audio/mpeg"}, b"\xff\xfb\x90\x00"),
        (
            {"Content-Type": "audio/mpeg"},
            b"ID3\x04\x00\x00\x00\x00\x00\x08not-audio",
        ),
        (
            {"Content-Type": "audio/wav"},
            b"RIFF\x00\x00\x00\x00WAVEinvalid",
        ),
    ],
)
async def test_dify_tts_client_rejects_invalid_success_response(
    headers: dict[str, str],
    content: bytes,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, content=content)

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=1024,
        )
        with pytest.raises(DifyProtocolError):
            await client.synthesize(text="测试", user="user")


async def test_dify_tts_client_rejects_response_over_size_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/mpeg"},
            content=b"ID3" + b"x" * 64,
        )

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyTextToSpeechClient(
            http_client=http_client,
            api_key="chat-test-key",
            max_response_bytes=16,
        )
        with pytest.raises(DifyProtocolError):
            await client.synthesize(text="测试", user="user")
