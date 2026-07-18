from uuid import uuid4

import pytest

from app.ai.dify.exceptions import DifyConfigurationError
from app.ai.dify.factory import DifyDatasetClientFactory


async def test_dify_factory_accepts_normal_server_configuration() -> None:
    factory = DifyDatasetClientFactory(
        base_url=" http://dify.test/v1/ ",
        api_key=" dataset-test-key ",
        dataset_id=str(uuid4()),
        timeout_seconds=30,
    )

    async with factory.open() as client:
        assert client is not None


@pytest.mark.parametrize(
    ("base_url", "api_key", "dataset_id", "timeout_seconds"),
    [
        ("", "key", str(uuid4()), 30),
        ("ftp://dify.test/v1", "key", str(uuid4()), 30),
        ("http://user:password@dify.test/v1", "key", str(uuid4()), 30),
        ("http://dify.test/v1?x=1", "key", str(uuid4()), 30),
        ("http://dify.test/v1#fragment", "key", str(uuid4()), 30),
        ("http://dify.test/v1", "", str(uuid4()), 30),
        ("http://dify.test/v1", "key", "not-a-uuid", 30),
        ("http://dify.test/v1", "key", str(uuid4()), 0),
    ],
)
async def test_dify_factory_rejects_unsafe_or_incomplete_configuration(
    base_url: str,
    api_key: str,
    dataset_id: str,
    timeout_seconds: float,
) -> None:
    factory = DifyDatasetClientFactory(
        base_url=base_url,
        api_key=api_key,
        dataset_id=dataset_id,
        timeout_seconds=timeout_seconds,
    )

    with pytest.raises(DifyConfigurationError):
        async with factory.open():
            pass
