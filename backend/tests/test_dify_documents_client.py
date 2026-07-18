import json
from uuid import uuid4

import httpx
import pytest

from app.ai.dify.client import DifyDatasetClient
from app.ai.dify.exceptions import DifyNotFoundError, DifyProtocolError


async def test_create_document_uses_canonical_file_contract() -> None:
    dataset_id = str(uuid4())
    document_id = str(uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/v1/datasets/{dataset_id}/document/create-by-file"
        assert request.headers["Authorization"] == "Bearer dataset-test-key"
        assert request.headers["Content-Type"].startswith("multipart/form-data;")
        body = request.content.decode("utf-8", errors="ignore")
        assert 'name="file"; filename="rules.txt"' in body
        assert "text/plain" in body
        assert "indexing_technique" in body
        assert "economy" in body
        assert "text_model" in body
        assert "Chinese" in body
        assert "automatic" in body
        assert "教学文档" in body
        return httpx.Response(
            200,
            json={
                "document": {
                    "id": document_id,
                    "name": "rules.txt",
                    "indexing_status": "waiting",
                },
                "batch": "batch-create",
            },
        )

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id=dataset_id,
        )
        result = await client.create_document_by_file(
            filename="rules.txt",
            media_type="text/plain",
            content="教学文档".encode(),
        )

    assert result.document_id == document_id
    assert result.indexing_status == "waiting"
    assert result.batch == "batch-create"


async def test_update_document_uses_canonical_patch_contract() -> None:
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    replacement_id = str(uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == f"/v1/datasets/{dataset_id}/documents/{document_id}"
        body = request.content.decode("utf-8", errors="ignore")
        assert 'name="file"; filename="rules.docx"' in body
        assert "application/vnd.openxmlformats-officedocument" in body
        return httpx.Response(
            200,
            json={
                "document": {
                    "id": replacement_id,
                    "indexing_status": "indexing",
                },
                "batch": "batch-update",
            },
        )

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id=dataset_id,
        )
        result = await client.update_document_by_file(
            document_id=document_id,
            filename="rules.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=b"docx-content",
        )

    assert result.document_id == replacement_id
    assert result.indexing_status == "indexing"
    assert result.batch == "batch-update"


async def test_indexing_status_returns_only_safe_normalized_fields() -> None:
    dataset_id = str(uuid4())
    document_id = str(uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == (
            f"/v1/datasets/{dataset_id}/documents/batch-status/indexing-status"
        )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": document_id,
                        "indexing_status": "completed",
                        "error": "sensitive upstream detail",
                        "completed_segments": 3,
                        "total_segments": 3,
                        "internal": "ignored",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id=dataset_id,
        )
        statuses = await client.get_document_indexing_status(batch="batch-status")

    assert statuses[0].document_id == document_id
    assert statuses[0].indexing_status == "completed"
    assert statuses[0].error_present is True
    assert statuses[0].completed_segments == 3
    assert statuses[0].total_segments == 3
    assert "sensitive" not in repr(statuses[0])


async def test_delete_document_accepts_http_204() -> None:
    dataset_id = str(uuid4())
    document_id = str(uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == f"/v1/datasets/{dataset_id}/documents/{document_id}"
        return httpx.Response(204)

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id=dataset_id,
        )
        await client.delete_document(document_id=document_id)


async def test_document_client_maps_not_found_without_response_body() -> None:
    dataset_id = str(uuid4())
    document_id = str(uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "sensitive upstream detail"})

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id=dataset_id,
        )
        with pytest.raises(DifyNotFoundError) as captured:
            await client.delete_document(document_id=document_id)

    assert "sensitive" not in str(captured.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"document": {"id": str(uuid4()), "indexing_status": "waiting"}},
        {"document": {"id": "not-a-uuid", "indexing_status": "waiting"}, "batch": "x"},
        {"document": {"id": str(uuid4()), "indexing_status": "unknown"}, "batch": "x"},
        {"data": []},
        {
            "data": [
                {
                    "id": str(uuid4()),
                    "indexing_status": "completed",
                    "completed_segments": 2,
                    "total_segments": 1,
                }
            ]
        },
    ],
)
async def test_document_client_rejects_invalid_success_payload(payload: dict) -> None:
    dataset_id = str(uuid4())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload))

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id=dataset_id,
        )
        with pytest.raises(DifyProtocolError):
            if "data" in payload:
                await client.get_document_indexing_status(batch="batch")
            else:
                await client.create_document_by_file(
                    filename="rules.txt",
                    media_type="text/plain",
                    content=b"rules",
                )
