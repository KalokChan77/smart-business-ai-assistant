from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.audio.dependencies import get_audio_service
from app.audio.schemas import TextToSpeechRequest
from app.audio.service import AudioService
from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal

router = APIRouter(prefix="/audio", tags=["audio"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
AudioServiceDependency = Annotated[AudioService, Depends(get_audio_service)]


@router.post(
    "/tts",
    response_class=Response,
    responses={
        200: {
            "description": "文字转语音成功",
            "content": {
                "audio/mpeg": {},
                "audio/wav": {},
            },
        }
    },
    summary="把短文本转换为语音",
)
async def synthesize_speech(
    payload: TextToSpeechRequest,
    principal: CurrentPrincipal,
    service: AudioServiceDependency,
) -> Response:
    audio = await service.synthesize(principal, payload)
    return Response(
        content=audio.content,
        media_type=audio.media_type,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
