from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx

from app.ai.dify.client import DifyDatasetClient
from app.ai.dify.exceptions import DifyConfigurationError


class DifyDatasetClientFactory:
    """Validate server-side Dataset settings and open short-lived HTTP clients."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        dataset_id: str,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._dataset_id = dataset_id
        self._timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def open(self) -> AsyncIterator[DifyDatasetClient]:
        base_url, api_key, dataset_id = self._validated_configuration()
        async with httpx.AsyncClient(
            base_url=f"{base_url}/",
            timeout=self._timeout_seconds,
            trust_env=False,
        ) as http_client:
            yield DifyDatasetClient(
                http_client=http_client,
                api_key=api_key,
                dataset_id=dataset_id,
            )

    def _validated_configuration(self) -> tuple[str, str, str]:
        base_url = self._base_url.strip().rstrip("/")
        api_key = self._api_key.strip()
        dataset_id = self._dataset_id.strip()

        if not base_url:
            raise DifyConfigurationError("Dify base URL is not configured.")
        try:
            parsed_url = httpx.URL(base_url)
        except Exception as exc:
            raise DifyConfigurationError("Dify base URL is invalid.") from exc
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.host
            or parsed_url.userinfo
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise DifyConfigurationError("Dify base URL is invalid.")

        if not api_key:
            raise DifyConfigurationError("Dify Dataset is not configured.")
        try:
            normalized_dataset_id = str(UUID(dataset_id))
        except (ValueError, AttributeError) as exc:
            raise DifyConfigurationError("Dify Dataset is not configured.") from exc
        if self._timeout_seconds <= 0:
            raise DifyConfigurationError("Dify timeout is invalid.")
        return base_url, api_key, normalized_dataset_id
