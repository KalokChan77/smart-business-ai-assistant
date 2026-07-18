import json

import httpx
import pytest

from app.ai.dify.client import DifyDatasetClient
from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyProtocolError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyTimeoutError,
    DifyUnavailableError,
)


async def test_dify_dataset_client_sends_fixed_economy_retrieval_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/datasets/dataset-id/retrieve"
        assert request.headers["Authorization"] == "Bearer dataset-test-key"
        payload = json.loads(request.content)
        assert payload == {
            "query": "退款条件是什么？",
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
        }
        return httpx.Response(
            200,
            json={
                "query": {"content": "退款条件是什么？"},
                "records": [
                    {
                        "score": 0.25,
                        "segment": {
                            "content": " 支付后 7 个自然日内可申请。 ",
                            "document": {
                                "id": "6d05bafc-e748-4b20-8f43-2efd9e1186c1",
                                "name": "退款规则.md",
                            },
                        },
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=transport,
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id="dataset-id",
        )
        records = await client.retrieve("退款条件是什么？")

    assert len(records) == 1
    assert records[0].document_id == "6d05bafc-e748-4b20-8f43-2efd9e1186c1"
    assert records[0].document_name == "退款规则.md"
    assert records[0].content == "支付后 7 个自然日内可申请。"
    assert records[0].score == 0.25


async def test_dify_dataset_client_hides_zero_keyword_relevance_score() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "score": 0.0,
                        "segment": {
                            "content": "支付后 7 个自然日内可申请。",
                            "document": {
                                "id": "6d05bafc-e748-4b20-8f43-2efd9e1186c1",
                                "name": "退款规则.md",
                            },
                        },
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
            dataset_id="dataset-id",
        )
        records = await client.retrieve("退款条件是什么？")

    assert records[0].score is None


async def test_dify_dataset_client_accepts_empty_records_as_no_match() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"records": []})

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id="dataset-id",
        )
        records = await client.retrieve("没有答案的问题")

    assert records == ()


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, DifyAuthenticationError),
        (403, DifyAuthenticationError),
        (429, DifyRateLimitError),
        (500, DifyUnavailableError),
        (503, DifyUnavailableError),
        (400, DifyRejectedError),
    ],
)
async def test_dify_dataset_client_maps_http_failures_without_response_body(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="sensitive upstream response")

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id="dataset-id",
        )
        with pytest.raises(expected_error) as captured:
            await client.retrieve("退款条件是什么？")

    assert "sensitive" not in str(captured.value)


async def test_dify_dataset_client_maps_timeout_without_upstream_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive timeout detail", request=request)

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id="dataset-id",
        )
        with pytest.raises(DifyTimeoutError) as captured:
            await client.retrieve("退款条件是什么？")

    assert "sensitive" not in str(captured.value)


async def test_dify_dataset_client_maps_network_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id="dataset-id",
        )
        with pytest.raises(DifyUnavailableError):
            await client.retrieve("退款条件是什么？")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"unexpected": []}),
        httpx.Response(200, json={"records": [{"score": 0.1}]}),
        httpx.Response(
            200,
            json={
                "records": [
                    {
                        "score": 0.1,
                        "segment": {
                            "content": "   ",
                            "document": {
                                "id": "971eab6e-a153-4513-af80-bc862925d4c2",
                                "name": "empty.md",
                            },
                        },
                    }
                ]
            },
        ),
    ],
)
async def test_dify_dataset_client_rejects_invalid_success_payload(
    response: httpx.Response,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response

    async with httpx.AsyncClient(
        base_url="http://dify.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DifyDatasetClient(
            http_client=http_client,
            api_key="dataset-test-key",
            dataset_id="dataset-id",
        )
        with pytest.raises(DifyProtocolError):
            await client.retrieve("退款条件是什么？")
