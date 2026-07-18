import json
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.ai.dify.exceptions import (
    DifyProtocolError,
    DifyTimeoutError,
    DifyUnavailableError,
)
from app.ai.dify.http import raise_for_dify_status
from app.ai.dify.schemas import (
    DifyDocumentIndexingStatus,
    DifyDocumentIndexingStatusResponsePayload,
    DifyDocumentMutationResponsePayload,
    DifyDocumentMutationResult,
    DifyRetrievalRecord,
    DifyRetrieveResponsePayload,
)

_ECONOMY_RETRIEVAL_MODEL: dict[str, object] = {
    "search_method": "keyword_search",
    "reranking_enable": False,
    "reranking_model": {
        "reranking_provider_name": "",
        "reranking_model_name": "",
    },
    "top_k": 5,
    "score_threshold_enabled": False,
    "score_threshold": None,
}

_ECONOMY_DOCUMENT_CONFIGURATION: dict[str, object] = {
    "indexing_technique": "economy",
    "doc_form": "text_model",
    "doc_language": "Chinese",
    "process_rule": {"mode": "automatic"},
}


class DifyDatasetClient:
    """Adapt the Dify Dataset retrieval API into stable domain records."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        api_key: str,
        dataset_id: str,
    ) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._dataset_id = dataset_id

    async def retrieve(self, query: str) -> tuple[DifyRetrievalRecord, ...]:
        dataset_id = quote(self._dataset_id, safe="")
        response = await self._request(
            "POST",
            f"datasets/{dataset_id}/retrieve",
            json={
                "query": query,
                "retrieval_model": _ECONOMY_RETRIEVAL_MODEL,
            },
        )
        payload = self._parse_retrieval_payload(response)
        records = tuple(
            DifyRetrievalRecord(
                document_id=str(record.segment.document.id),
                document_name=(
                    record.segment.document.name.strip()
                    if record.segment.document.name is not None
                    and record.segment.document.name.strip()
                    else "未命名文档"
                ),
                content=record.segment.content.strip(),
                score=(None if record.score == 0 else record.score),
            )
            for record in payload.records
            if record.segment.content.strip()
        )
        if payload.records and not records:
            raise DifyProtocolError("Dify retrieval records contain no content.")
        return records

    async def create_document_by_file(
        self,
        *,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> DifyDocumentMutationResult:
        dataset_id = quote(self._dataset_id, safe="")
        response = await self._request(
            "POST",
            f"datasets/{dataset_id}/document/create-by-file",
            data={"data": self._document_configuration_json()},
            files={"file": (filename, content, media_type)},
        )
        return self._parse_document_mutation_payload(response)

    async def update_document_by_file(
        self,
        *,
        document_id: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> DifyDocumentMutationResult:
        dataset_id = quote(self._dataset_id, safe="")
        escaped_document_id = quote(document_id, safe="")
        response = await self._request(
            "PATCH",
            f"datasets/{dataset_id}/documents/{escaped_document_id}",
            data={"data": self._document_configuration_json()},
            files={"file": (filename, content, media_type)},
        )
        return self._parse_document_mutation_payload(response)

    async def get_document_indexing_status(
        self,
        *,
        batch: str,
    ) -> tuple[DifyDocumentIndexingStatus, ...]:
        dataset_id = quote(self._dataset_id, safe="")
        escaped_batch = quote(batch, safe="")
        response = await self._request(
            "GET",
            f"datasets/{dataset_id}/documents/{escaped_batch}/indexing-status",
        )
        payload = self._parse_indexing_status_payload(response)
        if not payload.data:
            raise DifyProtocolError("Dify indexing status contains no documents.")
        return tuple(
            DifyDocumentIndexingStatus(
                document_id=str(item.id),
                indexing_status=item.indexing_status,
                error_present=bool(item.error),
                completed_segments=item.completed_segments,
                total_segments=item.total_segments,
            )
            for item in payload.data
        )

    async def delete_document(self, *, document_id: str) -> None:
        dataset_id = quote(self._dataset_id, safe="")
        escaped_document_id = quote(document_id, safe="")
        await self._request(
            "DELETE",
            f"datasets/{dataset_id}/documents/{escaped_document_id}",
        )

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        try:
            response = await self._http_client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {self._api_key}"},
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise DifyTimeoutError("Dify request timed out.") from exc
        except httpx.RequestError as exc:
            raise DifyUnavailableError("Dify request failed.") from exc
        raise_for_dify_status(response)
        return response

    @staticmethod
    def _parse_retrieval_payload(
        response: httpx.Response,
    ) -> DifyRetrieveResponsePayload:
        try:
            raw_payload = response.json()
            return DifyRetrieveResponsePayload.model_validate(raw_payload)
        except (ValueError, ValidationError) as exc:
            raise DifyProtocolError("Dify returned an invalid response.") from exc

    @staticmethod
    def _parse_document_mutation_payload(
        response: httpx.Response,
    ) -> DifyDocumentMutationResult:
        try:
            raw_payload = response.json()
            payload = DifyDocumentMutationResponsePayload.model_validate(raw_payload)
        except (ValueError, ValidationError) as exc:
            raise DifyProtocolError("Dify returned an invalid response.") from exc
        return DifyDocumentMutationResult(
            document_id=str(payload.document.id),
            indexing_status=payload.document.indexing_status,
            batch=payload.batch,
        )

    @staticmethod
    def _parse_indexing_status_payload(
        response: httpx.Response,
    ) -> DifyDocumentIndexingStatusResponsePayload:
        try:
            raw_payload = response.json()
            return DifyDocumentIndexingStatusResponsePayload.model_validate(raw_payload)
        except (ValueError, ValidationError) as exc:
            raise DifyProtocolError("Dify returned an invalid response.") from exc

    @staticmethod
    def _document_configuration_json() -> str:
        return json.dumps(
            _ECONOMY_DOCUMENT_CONFIGURATION,
            ensure_ascii=False,
            separators=(",", ":"),
        )
