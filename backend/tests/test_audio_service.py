from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyConfigurationError,
    DifyProtocolError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.audio.ports import SynthesizedAudio
from app.audio.schemas import TextToSpeechRequest
from app.audio.service import AudioService
from app.auth.principal import Principal
from app.core.errors import AppError


class RecordingGateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.text: str | None = None
        self.user: str | None = None

    async def synthesize(self, *, text: str, user: str) -> SynthesizedAudio:
        self.text = text
        self.user = user
        if self.error is not None:
            raise self.error
        return SynthesizedAudio(content=b"RIFF-audio", media_type="audio/wav")


class FakeGatewayProvider:
    def __init__(
        self,
        gateway: RecordingGateway,
        open_error: Exception | None = None,
    ) -> None:
        self.gateway = gateway
        self.open_error = open_error

    @asynccontextmanager
    async def open(self):
        if self.open_error is not None:
            raise self.open_error
        yield self.gateway


def make_principal(*, user_id=None, tenant_id=None) -> Principal:
    return Principal(
        user_id=user_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        username="demo",
        email="demo@example.com",
        roles=frozenset({"user"}),
    )


async def test_audio_service_builds_stable_pseudonymous_user_alias() -> None:
    principal = make_principal()
    gateway = RecordingGateway()
    service = AudioService(FakeGatewayProvider(gateway))

    result = await service.synthesize(
        principal,
        TextToSpeechRequest(text="语音测试"),
    )
    first_alias = gateway.user
    await service.synthesize(principal, TextToSpeechRequest(text="再次测试"))

    assert result.media_type == "audio/wav"
    assert gateway.text == "再次测试"
    assert gateway.user == first_alias
    assert first_alias is not None
    assert first_alias.startswith("smart-business-")
    assert str(principal.user_id) not in first_alias
    assert str(principal.tenant_id) not in first_alias


async def test_audio_service_alias_changes_between_users() -> None:
    tenant_id = uuid4()
    first_gateway = RecordingGateway()
    second_gateway = RecordingGateway()

    await AudioService(FakeGatewayProvider(first_gateway)).synthesize(
        make_principal(tenant_id=tenant_id),
        TextToSpeechRequest(text="第一个用户"),
    )
    await AudioService(FakeGatewayProvider(second_gateway)).synthesize(
        make_principal(tenant_id=tenant_id),
        TextToSpeechRequest(text="第二个用户"),
    )

    assert first_gateway.user != second_gateway.user


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "raise_on_open"),
    [
        (
            DifyConfigurationError("sensitive configuration"),
            503,
            "audio_service_not_configured",
            True,
        ),
        (
            DifyAuthenticationError("sensitive authentication"),
            502,
            "audio_upstream_authentication_failed",
            False,
        ),
        (
            DifyRateLimitError("sensitive rate limit"),
            503,
            "audio_upstream_rate_limited",
            False,
        ),
        (
            DifyTimeoutError("sensitive timeout"),
            504,
            "audio_upstream_timeout",
            False,
        ),
        (
            DifyUnavailableError("sensitive unavailable"),
            502,
            "audio_upstream_unavailable",
            False,
        ),
        (
            DifyRejectedError("sensitive rejected"),
            502,
            "audio_upstream_rejected",
            False,
        ),
        (
            DifyProtocolError("sensitive protocol"),
            502,
            "audio_upstream_protocol_error",
            False,
        ),
    ],
)
async def test_audio_service_maps_upstream_errors_without_detail(
    error: Exception,
    expected_status: int,
    expected_code: str,
    raise_on_open: bool,
) -> None:
    gateway = RecordingGateway(None if raise_on_open else error)
    provider = FakeGatewayProvider(
        gateway,
        open_error=error if raise_on_open else None,
    )
    service = AudioService(provider)

    with pytest.raises(AppError) as captured:
        await service.synthesize(
            make_principal(),
            TextToSpeechRequest(text="语音测试"),
        )

    assert captured.value.status_code == expected_status
    assert captured.value.code == expected_code
    assert "sensitive" not in captured.value.message
