from typing import Literal

from fastapi import status

from app.ai.providers.base import ChatProvider
from app.ai.providers.dashscope import DashScopeProvider
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import Settings
from app.core.errors import AppError

ProviderName = Literal["deepseek", "dashscope"]


class ProviderFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, requested: ProviderName | None = None) -> ChatProvider:
        provider = requested or self._settings.llm_provider
        if provider == "deepseek":
            api_key = self._secret(self._settings.deepseek_api_key)
            if api_key is None:
                raise self._not_configured(provider)
            return DeepSeekProvider(
                api_key=api_key,
                base_url=self._required(self._settings.deepseek_base_url, provider),
                model=self._required(self._settings.deepseek_chat_model, provider),
                timeout_seconds=self._settings.ai_request_timeout_seconds,
            )

        api_key = self._secret(self._settings.dashscope_api_key)
        if api_key is None:
            raise self._not_configured(provider)
        workspace_id = (self._settings.bailian_workspace_id or "").strip() or None
        return DashScopeProvider(
            api_key=api_key,
            base_url=self._required(self._settings.dashscope_base_url, provider),
            model=self._required(self._settings.dashscope_chat_model, provider),
            workspace_id=workspace_id,
        )

    @staticmethod
    def _secret(value) -> str | None:
        if value is None:
            return None
        normalized = value.get_secret_value().strip()
        return normalized or None

    @staticmethod
    def _required(value: str, provider: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ProviderFactory._not_configured(provider)
        return normalized

    @staticmethod
    def _not_configured(provider: str) -> AppError:
        return AppError(
            code="ai_provider_not_configured",
            message="所选模型服务尚未完成配置。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"provider": provider},
        )
