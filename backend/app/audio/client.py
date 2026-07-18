import io
import wave

import httpx

from app.ai.dify.exceptions import (
    DifyClientError,
    DifyProtocolError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.ai.dify.http import raise_for_dify_status
from app.audio.ports import SynthesizedAudio

_MP3_MEDIA_TYPE = "audio/mpeg"
_WAV_MEDIA_TYPE = "audio/wav"
_MP3_FRAME_SCAN_LIMIT = 4096

_MPEG1_BITRATES = {
    1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    2: (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    3: (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
}
_MPEG2_BITRATES = {
    1: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    3: (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
}
_MPEG_SAMPLE_RATES = {
    0: (11_025, 12_000, 8_000),
    2: (22_050, 24_000, 16_000),
    3: (44_100, 48_000, 32_000),
}


class DifyTextToSpeechClient:
    """Adapt Dify's TTS Service API into validated platform audio."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        api_key: str,
        max_response_bytes: int,
    ) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._max_response_bytes = max_response_bytes

    async def synthesize(
        self,
        *,
        text: str,
        user: str,
    ) -> SynthesizedAudio:
        try:
            async with self._http_client.stream(
                "POST",
                "text-to-audio",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"text": text, "user": user},
            ) as response:
                raise_for_dify_status(response)
                self._validate_declared_media_type(response)
                self._validate_declared_size(response)
                content = await self._read_limited_content(response)
        except DifyClientError:
            raise
        except httpx.TimeoutException as exc:
            raise DifyTimeoutError("Dify request timed out.") from exc
        except httpx.RequestError as exc:
            raise DifyUnavailableError("Dify request failed.") from exc

        media_type = self._detect_media_type(content)
        return SynthesizedAudio(content=content, media_type=media_type)

    @staticmethod
    def _validate_declared_media_type(response: httpx.Response) -> None:
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not media_type.strip().lower().startswith("audio/"):
            raise DifyProtocolError("Dify returned a non-audio response.")

    def _validate_declared_size(self, response: httpx.Response) -> None:
        raw_length = response.headers.get("content-length")
        if raw_length is None:
            return
        try:
            declared_length = int(raw_length)
        except ValueError:
            return
        if declared_length > self._max_response_bytes:
            raise DifyProtocolError("Dify audio response is too large.")

    async def _read_limited_content(self, response: httpx.Response) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > self._max_response_bytes:
                raise DifyProtocolError("Dify audio response is too large.")
            content.extend(chunk)
        if not content:
            raise DifyProtocolError("Dify returned an empty audio response.")
        return bytes(content)

    @classmethod
    def _detect_media_type(cls, content: bytes) -> str:
        if cls._is_wave(content):
            return _WAV_MEDIA_TYPE
        if cls._is_mp3(content):
            return _MP3_MEDIA_TYPE
        raise DifyProtocolError("Dify returned an unsupported audio response.")

    @staticmethod
    def _is_wave(content: bytes) -> bool:
        if not (content.startswith(b"RIFF") and content[8:12] == b"WAVE"):
            return False
        try:
            with wave.open(io.BytesIO(content), "rb") as audio:
                return audio.getnchannels() > 0 and audio.getnframes() > 0
        except (EOFError, wave.Error):
            return False

    @staticmethod
    def _is_mp3(content: bytes) -> bool:
        frame_start = DifyTextToSpeechClient._mp3_frame_start(content)
        if frame_start is None:
            return False
        frame_length = DifyTextToSpeechClient._mp3_frame_length(
            content,
            frame_start,
        )
        return (
            frame_length is not None
            and frame_start + frame_length <= len(content)
        )

    @staticmethod
    def _mp3_frame_start(content: bytes) -> int | None:
        offset = 0
        if content.startswith(b"ID3"):
            if len(content) < 10:
                return None
            size_bytes = content[6:10]
            if any(value & 0x80 for value in size_bytes):
                return None
            tag_size = (
                (size_bytes[0] << 21)
                | (size_bytes[1] << 14)
                | (size_bytes[2] << 7)
                | size_bytes[3]
            )
            major_version = content[3]
            if major_version not in {2, 3, 4}:
                return None
            footer_size = 10 if major_version == 4 and content[5] & 0x10 else 0
            offset = 10 + tag_size + footer_size
            if offset > len(content):
                return None

        scan_end = min(len(content) - 3, offset + _MP3_FRAME_SCAN_LIMIT)
        for candidate in range(offset, max(offset, scan_end)):
            frame_length = DifyTextToSpeechClient._mp3_frame_length(
                content,
                candidate,
            )
            if frame_length and candidate + frame_length <= len(content):
                return candidate
        return None

    @staticmethod
    def _mp3_frame_length(content: bytes, offset: int) -> int | None:
        if offset < 0 or offset + 4 > len(content):
            return None
        header = int.from_bytes(content[offset : offset + 4], "big")
        if (header >> 21) & 0x7FF != 0x7FF:
            return None

        version = (header >> 19) & 0x03
        layer = (header >> 17) & 0x03
        bitrate_index = (header >> 12) & 0x0F
        sample_rate_index = (header >> 10) & 0x03
        padding = (header >> 9) & 0x01
        emphasis = header & 0x03
        if (
            version == 1
            or layer == 0
            or bitrate_index in {0, 15}
            or sample_rate_index == 3
            or emphasis == 2
        ):
            return None

        bitrate_table = _MPEG1_BITRATES if version == 3 else _MPEG2_BITRATES
        bitrate_kbps = bitrate_table[layer][bitrate_index]
        sample_rate = _MPEG_SAMPLE_RATES[version][sample_rate_index]
        if layer == 3:
            return ((12 * bitrate_kbps * 1000) // sample_rate + padding) * 4
        coefficient = 144 if layer == 2 or version == 3 else 72
        return (coefficient * bitrate_kbps * 1000) // sample_rate + padding
