import pytest

from app.ai.dify.exceptions import DifyConfigurationError
from app.audio.factory import DifyTextToSpeechClientFactory


async def test_dify_tts_factory_accepts_normal_server_configuration() -> None:
    factory = DifyTextToSpeechClientFactory(
        base_url=" http://dify.test/v1/ ",
        api_key=" chat-test-key ",
        timeout_seconds=30,
        max_response_bytes=1024,
    )

    async with factory.open() as client:
        assert client is not None


@pytest.mark.parametrize(
    ("base_url", "api_key", "timeout_seconds", "max_response_bytes"),
    [
        ("", "key", 30, 1024),
        ("ftp://dify.test/v1", "key", 30, 1024),
        ("http://user:password@dify.test/v1", "key", 30, 1024),
        ("http://dify.test/v1?x=1", "key", 30, 1024),
        ("http://dify.test/v1#fragment", "key", 30, 1024),
        ("http://dify.test/v1", "", 30, 1024),
        ("http://dify.test/v1", "key", 0, 1024),
        ("http://dify.test/v1", "key", 30, 0),
        ("http://dify.test/v1", "key", 30, 5 * 1024 * 1024 + 1),
    ],
)
async def test_dify_tts_factory_rejects_unsafe_or_incomplete_configuration(
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    max_response_bytes: int,
) -> None:
    factory = DifyTextToSpeechClientFactory(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )

    with pytest.raises(DifyConfigurationError):
        async with factory.open():
            pass
