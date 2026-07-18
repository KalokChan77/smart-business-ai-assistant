import hashlib

from fastapi import status

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyConfigurationError,
    DifyProtocolError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.audio.ports import SynthesizedAudio, TextToSpeechGatewayProvider
from app.audio.schemas import TextToSpeechRequest
from app.auth.principal import Principal
from app.core.errors import AppError


class AudioService:
    """Orchestrate authenticated text-to-speech without persisting audio."""

    def __init__(self, gateway_provider: TextToSpeechGatewayProvider) -> None:
        self._gateway_provider = gateway_provider

    async def synthesize(
        self,
        principal: Principal,
        request: TextToSpeechRequest,
    ) -> SynthesizedAudio:
        user_alias = self._build_user_alias(principal)
        try:
            async with self._gateway_provider.open() as gateway:
                return await gateway.synthesize(text=request.text, user=user_alias)
        except DifyConfigurationError as exc:
            raise AppError(
                code="audio_service_not_configured",
                message="语音合成服务尚未完成配置。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        except DifyAuthenticationError as exc:
            raise AppError(
                code="audio_upstream_authentication_failed",
                message="语音合成服务认证失败，请联系管理员检查服务端配置。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except DifyRateLimitError as exc:
            raise AppError(
                code="audio_upstream_rate_limited",
                message="语音合成服务当前请求较多，请稍后重试。",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        except DifyTimeoutError as exc:
            raise AppError(
                code="audio_upstream_timeout",
                message="语音合成服务响应超时，请稍后重试。",
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            ) from exc
        except DifyUnavailableError as exc:
            raise AppError(
                code="audio_upstream_unavailable",
                message="语音合成服务暂时不可用，请稍后重试。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except DifyRejectedError as exc:
            raise AppError(
                code="audio_upstream_rejected",
                message="语音合成服务未能处理本次请求。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        except DifyProtocolError as exc:
            raise AppError(
                code="audio_upstream_protocol_error",
                message="语音合成服务返回了无法识别的音频。",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

    @staticmethod
    def _build_user_alias(principal: Principal) -> str:
        source = f"{principal.tenant_id}:{principal.user_id}".encode()
        return f"smart-business-{hashlib.sha256(source).hexdigest()}"
