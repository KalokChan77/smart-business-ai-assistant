"""Verify configured Dify keys and economy retrieval without printing secrets."""

import asyncio
from uuid import uuid4

import httpx

from app.core.asyncio_compat import run_async
from app.core.config import Settings


def required_secret(value, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"{name} must be configured.")
    return value.get_secret_value().strip()


def response_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return f"http_{response.status_code}"
    if not isinstance(payload, dict):
        return f"http_{response.status_code}"
    return str(payload.get("code") or f"http_{response.status_code}")[:100]


async def verify() -> None:
    settings = Settings()
    base_url = settings.dify_base_url.rstrip("/")
    chat_key = required_secret(
        settings.dify_chat_app_api_key,
        "DIFY_CHAT_APP_API_KEY",
    )
    workflow_key = required_secret(
        settings.dify_workflow_api_key,
        "DIFY_WORKFLOW_API_KEY",
    )
    dataset_key = required_secret(
        settings.dify_dataset_api_key,
        "DIFY_DATASET_API_KEY",
    )
    dataset_id = (settings.dify_dataset_id or "").strip()
    if not dataset_id:
        raise RuntimeError("DIFY_DATASET_ID must be configured.")

    user = f"smart-business-verify-{uuid4().hex[:8]}"
    async with httpx.AsyncClient(
        timeout=settings.ai_request_timeout_seconds,
        trust_env=False,
    ) as client:
        chat = await client.post(
            f"{base_url}/chat-messages",
            headers={"Authorization": f"Bearer {chat_key}"},
            json={
                "inputs": {},
                "query": "请返回配置验证成功",
                "response_mode": "blocking",
                "conversation_id": "",
                "user": user,
            },
        )
        if not chat.is_success:
            raise AssertionError(f"Dify Chat failed: {response_error_code(chat)}")
        answer = chat.json().get("answer", "")
        if not str(answer).strip():
            raise AssertionError("Dify Chat returned an empty answer.")
        print(f"chat_key: PASS (status={chat.status_code}, answer_chars={len(str(answer))})")

        workflow = await client.post(
            f"{base_url}/workflows/run",
            headers={"Authorization": f"Bearer {workflow_key}"},
            json={
                "inputs": {"query": "生成配置验证摘要"},
                "response_mode": "blocking",
                "user": user,
            },
        )
        if not workflow.is_success:
            raise AssertionError(
                f"Dify Workflow failed: {response_error_code(workflow)}"
            )
        workflow_status = workflow.json().get("data", {}).get("status")
        if workflow_status != "succeeded":
            raise AssertionError("Dify Workflow did not succeed.")
        print(
            "workflow_key: PASS "
            f"(status={workflow.status_code}, workflow_status={workflow_status})"
        )

        datasets = await client.get(
            f"{base_url}/datasets",
            headers={"Authorization": f"Bearer {dataset_key}"},
            params={"page": 1, "limit": 20},
        )
        if not datasets.is_success:
            raise AssertionError(
                f"Dify Dataset list failed: {response_error_code(datasets)}"
            )
        dataset_items = datasets.json().get("data", [])
        target_found = any(
            isinstance(item, dict) and item.get("id") == dataset_id
            for item in dataset_items
        )
        if not target_found:
            raise AssertionError("Configured Dify dataset ID is not accessible.")
        print(
            "dataset_key: PASS "
            f"(status={datasets.status_code}, target_found={target_found})"
        )

        documents = await client.get(
            f"{base_url}/datasets/{dataset_id}/documents",
            headers={"Authorization": f"Bearer {dataset_key}"},
            params={"page": 1, "limit": 100},
        )
        if not documents.is_success:
            raise AssertionError(
                f"Dify document list failed: {response_error_code(documents)}"
            )
        document_items = documents.json().get("data", [])
        incomplete = [
            item
            for item in document_items
            if not isinstance(item, dict) or item.get("indexing_status") != "completed"
        ]
        if not document_items or incomplete:
            raise AssertionError("Dify knowledge documents are not fully indexed.")
        print(
            "dataset_documents: PASS "
            f"(completed={len(document_items)}, incomplete=0)"
        )

        retrieve = await client.post(
            f"{base_url}/datasets/{dataset_id}/retrieve",
            headers={"Authorization": f"Bearer {dataset_key}"},
            json={
                "query": "退款申请需要满足什么条件？",
                "retrieval_model": {
                    "search_method": "keyword_search",
                    "reranking_enable": False,
                    "reranking_model": {
                        "reranking_provider_name": "",
                        "reranking_model_name": "",
                    },
                    "top_k": 5,
                    "score_threshold_enabled": False,
                    "score_threshold": None,
                },
            },
        )
        if not retrieve.is_success:
            raise AssertionError(
                f"Dify retrieval failed: {response_error_code(retrieve)}"
            )
        records = retrieve.json().get("records", [])
        if not records:
            raise AssertionError("Dify economy retrieval returned no records.")
        print(
            "dataset_retrieve: PASS "
            f"(status={retrieve.status_code}, records={len(records)})"
        )


if __name__ == "__main__":
    run_async(verify())
