from typing import Annotated

from fastapi import Depends, Request

from app.audio.factory import DifyTextToSpeechClientFactory
from app.audio.service import AudioService


def get_dify_tts_client_factory(request: Request) -> DifyTextToSpeechClientFactory:
    settings = request.app.state.settings
    return DifyTextToSpeechClientFactory(
        base_url=settings.dify_base_url,
        api_key=(
            settings.dify_chat_app_api_key.get_secret_value().strip()
            if settings.dify_chat_app_api_key is not None
            else ""
        ),
        timeout_seconds=settings.dify_tts_timeout_seconds,
        max_response_bytes=settings.dify_tts_max_response_bytes,
    )


def get_audio_service(
    factory: Annotated[
        DifyTextToSpeechClientFactory,
        Depends(get_dify_tts_client_factory),
    ],
) -> AudioService:
    return AudioService(factory)
