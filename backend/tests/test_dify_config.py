import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_dify_credentials_are_loaded_as_secrets() -> None:
    settings = Settings(
        _env_file=None,
        dify_base_url="http://dify.test/v1",
        dify_chat_app_api_key="chat-test-value",
        dify_workflow_api_key="workflow-test-value",
        dify_dataset_api_key="dataset-test-value",
        dify_dataset_id="dataset-id",
        dify_tts_timeout_seconds=90,
        dify_tts_max_response_bytes=2 * 1024 * 1024,
    )

    assert settings.dify_base_url == "http://dify.test/v1"
    assert settings.dify_chat_app_api_key is not None
    assert settings.dify_chat_app_api_key.get_secret_value() == "chat-test-value"
    assert settings.dify_workflow_api_key is not None
    assert settings.dify_workflow_api_key.get_secret_value() == "workflow-test-value"
    assert settings.dify_dataset_api_key is not None
    assert settings.dify_dataset_api_key.get_secret_value() == "dataset-test-value"
    assert settings.dify_dataset_id == "dataset-id"
    assert settings.dify_tts_timeout_seconds == 90
    assert settings.dify_tts_max_response_bytes == 2 * 1024 * 1024
    assert "chat-test-value" not in repr(settings)


def test_dify_tts_response_limit_cannot_exceed_public_contract() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            dify_tts_max_response_bytes=5 * 1024 * 1024 + 1,
        )
