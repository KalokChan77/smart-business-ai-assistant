class DifyClientError(Exception):
    """Base class for safe, classified Dify client failures."""


class DifyConfigurationError(DifyClientError):
    """Required server-side Dify connection settings are missing or invalid."""


class DifyAuthenticationError(DifyClientError):
    """Dify rejected the configured service credential or permission."""


class DifyRateLimitError(DifyClientError):
    """Dify rate-limited the server-side request."""


class DifyTimeoutError(DifyClientError):
    """A Dify request exceeded its configured timeout."""


class DifyUnavailableError(DifyClientError):
    """Dify could not be reached or returned a server-side failure."""


class DifyRejectedError(DifyClientError):
    """Dify rejected a request for a non-authentication client reason."""


class DifyNotFoundError(DifyRejectedError):
    """The configured Dify Dataset resource no longer exists."""


class DifyProtocolError(DifyClientError):
    """Dify returned a successful response with an invalid public shape."""
