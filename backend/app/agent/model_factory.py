from dataclasses import dataclass

from fastapi import status
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_qwq import ChatQwen

from app.ai.schemas import ProviderName
from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True, slots=True)
class AgentModelBinding:
    provider: str
    model: str
    chat_model: BaseChatModel


class AgentModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, requested: ProviderName | None = None) -> AgentModelBinding:
        provider = requested or self._settings.llm_provider
        if provider == "deepseek":
            api_key = self._secret(self._settings.deepseek_api_key)
            model = self._required(self._settings.deepseek_chat_model, provider)
            if api_key is None:
                raise self._not_configured(provider)
            if model == "deepseek-reasoner":
                raise AppError(
                    code="agent_model_not_supported",
                    message="当前模型不支持本项目的工具调用 Agent。",
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
            chat_model = ChatDeepSeek(
                model=model,
                api_key=api_key,
                base_url=self._required(self._settings.deepseek_base_url, provider),
                temperature=0,
                streaming=True,
                stream_usage=True,
                timeout=self._settings.ai_request_timeout_seconds,
                max_retries=1,
            )
            return AgentModelBinding(provider, model, chat_model)

        api_key = self._secret(self._settings.dashscope_api_key)
        if api_key is None:
            raise self._not_configured(provider)
        model = self._required(self._settings.dashscope_chat_model, provider)
        chat_model = ChatQwen(
            model=model,
            api_key=api_key,
            base_url=self._required(
                self._settings.bailian_openai_base_url,
                provider,
            ),
            temperature=0,
            streaming=True,
            stream_usage=True,
            timeout=self._settings.ai_request_timeout_seconds,
            max_retries=1,
            enable_thinking=False,
        )
        return AgentModelBinding(provider, model, chat_model)

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
            raise AgentModelFactory._not_configured(provider)
        return normalized

    @staticmethod
    def _not_configured(provider: str) -> AppError:
        return AppError(
            code="ai_provider_not_configured",
            message="所选模型服务尚未完成配置。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"provider": provider},
        )
