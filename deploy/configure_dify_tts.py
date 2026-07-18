"""Idempotently enable the teaching Dify app's default TTS configuration.

Run inside the Dify API container:

    docker exec -i docker-api-1 python - < deploy/configure_dify_tts.py

The script uses Dify's own service layer and never reads or prints credentials.
"""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import app
from extensions.ext_database import db
from libs.datetime_utils import naive_utc_now
from models import Account, App, TenantAccountJoin, Workflow
from models.account import AccountStatus
from services.model_provider_service import ModelProviderService
from services.workflow_service import WorkflowService

APP_NAME = "智慧商务教学问答"
TTS_MODEL_TYPE = "tts"
TTS_PROVIDER = "langgenius/tongyi/tongyi"
TTS_MODEL = "qwen3-tts-flash"
TTS_VOICE = "Cherry"
TTS_LANGUAGE = "zh-Hans"


def _load_unique_app() -> App:
    matches = db.session.scalars(select(App).where(App.name == APP_NAME)).all()
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one target Dify app, found {len(matches)}."
        )
    return matches[0]


def _load_active_editor(target: App) -> Account:
    preferred_ids = tuple(
        identifier
        for identifier in (target.updated_by, target.maintainer, target.created_by)
        if identifier
    )
    base_statement = (
        select(Account)
        .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
        .where(
            TenantAccountJoin.tenant_id == target.tenant_id,
            Account.status == AccountStatus.ACTIVE,
        )
    )

    for account_id in preferred_ids:
        account = db.session.scalar(
            base_statement.where(Account.id == account_id).limit(1)
        )
        if account is not None:
            account.set_tenant_id(target.tenant_id)
            return account

    account = db.session.scalar(base_statement.order_by(Account.created_at).limit(1))
    if account is None:
        raise RuntimeError("No active account exists in the target Dify workspace.")
    account.set_tenant_id(target.tenant_id)
    return account


def _target_features(original: dict) -> dict:
    features = deepcopy(original)
    text_to_speech = dict(features.get("text_to_speech") or {})
    text_to_speech.update(
        {
            "enabled": True,
            "voice": TTS_VOICE,
            "language": TTS_LANGUAGE,
        }
    )
    features["text_to_speech"] = text_to_speech
    return features


def _tts_is_desired(features: dict) -> bool:
    text_to_speech = features.get("text_to_speech") or {}
    return (
        text_to_speech.get("enabled") is True
        and text_to_speech.get("voice") == TTS_VOICE
        and text_to_speech.get("language") == TTS_LANGUAGE
    )


def _without_tts(features: dict) -> dict:
    normalized = deepcopy(features)
    normalized.pop("text_to_speech", None)
    return normalized


def _assert_no_unrelated_draft_changes(draft: Workflow, published: Workflow | None) -> None:
    if published is None:
        return
    unrelated_change = any(
        (
            draft.type != published.type,
            draft.graph_dict != published.graph_dict,
            draft.environment_variables != published.environment_variables,
            draft.conversation_variables != published.conversation_variables,
            draft.rag_pipeline_variables != published.rag_pipeline_variables,
            _without_tts(draft.features_dict)
            != _without_tts(published.features_dict),
        )
    )
    if unrelated_change:
        raise RuntimeError(
            "The draft contains unrelated unpublished changes; refusing to publish."
        )


def configure() -> None:
    with app.app_context():
        target = _load_unique_app()
        account = _load_active_editor(target)
        workflow_service = WorkflowService()
        draft = workflow_service.get_draft_workflow(app_model=target)
        if draft is None:
            raise RuntimeError("The target Dify app has no draft workflow.")

        current_published = target.workflow
        _assert_no_unrelated_draft_changes(draft, current_published)
        original_features = deepcopy(draft.features_dict)
        desired_features = _target_features(original_features)
        feature_changed = desired_features != original_features
        publish_required = feature_changed or not (
            current_published is not None
            and _tts_is_desired(current_published.features_dict)
        )

        ModelProviderService().update_default_model_of_model_type(
            target.tenant_id,
            TTS_MODEL_TYPE,
            TTS_PROVIDER,
            TTS_MODEL,
        )

        if feature_changed:
            workflow_service.update_draft_workflow_features(
                app_model=target,
                features=desired_features,
                account=account,
            )

        if publish_required:
            with sessionmaker(db.engine).begin() as session:
                target_in_session = session.get(App, target.id)
                if target_in_session is None:
                    raise RuntimeError(
                        "The target Dify app disappeared during publishing."
                    )
                published = workflow_service.publish_workflow(
                    session=session,
                    app_model=target_in_session,
                    account=account,
                    marked_name="启用通义文字转语音",
                    marked_comment="由教学项目配置脚本发布。",
                )
                target_in_session.workflow_id = published.id
                target_in_session.updated_by = account.id
                target_in_session.updated_at = naive_utc_now()

        db.session.expire_all()
        verified = _load_unique_app()
        verified_draft = workflow_service.get_draft_workflow(app_model=verified)
        verified_published = verified.workflow
        draft_tts = (
            verified_draft.features_dict.get("text_to_speech", {})
            if verified_draft is not None
            else {}
        )
        published_tts = (
            verified_published.features_dict.get("text_to_speech", {})
            if verified_published is not None
            else {}
        )

        print("dify_tts_configuration=success")
        print(f"published_new_version={publish_required}")
        print(f"draft_tts_enabled={bool(draft_tts.get('enabled'))}")
        print(f"published_tts_enabled={bool(published_tts.get('enabled'))}")
        print(f"voice_configured={bool(str(published_tts.get('voice') or '').strip())}")
        print(
            "language_configured="
            f"{bool(str(published_tts.get('language') or '').strip())}"
        )


if __name__ == "__main__":
    configure()
