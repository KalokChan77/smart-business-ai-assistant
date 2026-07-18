from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "东软智慧商务 AI 助手平台"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: SecretStr | None = None
    database_echo: bool = False
    redis_url: SecretStr | None = None
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "smart-business-ai-backend"
    jwt_audience: str = "smart-business-ai-web"
    jwt_access_ttl_minutes: int = Field(default=30, ge=1, le=1440)
    jwt_refresh_ttl_days: int = Field(default=7, ge=1, le=30)

    llm_provider: Literal["deepseek", "dashscope"] = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    bailian_openai_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    dashscope_chat_model: str = "qwen-plus"
    bailian_workspace_id: str | None = None
    ai_request_timeout_seconds: float = Field(default=120.0, ge=5.0, le=600.0)
    ai_history_message_limit: int = Field(default=50, ge=1, le=200)
    agent_history_message_limit: int = Field(default=30, ge=1, le=100)
    agent_recursion_limit: int = Field(default=8, ge=3, le=30)

    dify_base_url: str = "http://localhost:18080/v1"
    dify_chat_app_api_key: SecretStr | None = None
    dify_workflow_api_key: SecretStr | None = None
    dify_dataset_api_key: SecretStr | None = None
    dify_dataset_id: str | None = None
    dify_tts_timeout_seconds: float = Field(default=120.0, ge=5.0, le=600.0)
    dify_tts_max_response_bytes: int = Field(
        default=5 * 1024 * 1024,
        ge=1024,
        le=5 * 1024 * 1024,
    )

    knowledge_upload_dir: Path = _BACKEND_ROOT / ".data" / "knowledge_documents"
    knowledge_max_upload_bytes: int = Field(
        default=15 * 1024 * 1024,
        ge=1024,
        le=100 * 1024 * 1024,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
