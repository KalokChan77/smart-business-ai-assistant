import httpx

from app.ai.dify.exceptions import (
    DifyAuthenticationError,
    DifyNotFoundError,
    DifyRateLimitError,
    DifyRejectedError,
    DifyUnavailableError,
)


def raise_for_dify_status(response: httpx.Response) -> None:
    """Map upstream HTTP status without exposing the response body."""

    if response.is_success:
        return
    if response.status_code in {401, 403}:
        raise DifyAuthenticationError("Dify authentication failed.")
    if response.status_code == 404:
        raise DifyNotFoundError("Dify resource was not found.")
    if response.status_code == 429:
        raise DifyRateLimitError("Dify rate limit reached.")
    if response.status_code >= 500:
        raise DifyUnavailableError("Dify server is unavailable.")
    raise DifyRejectedError("Dify rejected the request.")
