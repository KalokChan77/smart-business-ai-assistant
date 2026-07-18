import logging
from time import perf_counter

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import internal_error_response
from app.core.request_context import (
    REQUEST_ID_HEADER,
    bind_request_id,
    reset_request_id,
    resolve_request_id,
)

logger = logging.getLogger("app.http")


class RequestContextMiddleware:
    """Attach request context and structured access logs without buffering bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming_headers = Headers(scope=scope)
        request_id = resolve_request_id(incoming_headers.get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        token = bind_request_id(request_id)
        started_at = perf_counter()
        response_started = False
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            # Keep the catch-all inside this middleware so request context is still
            # bound when an unknown failure is logged and converted to a safe 500.
            # Once a streaming response has started, re-raise instead of appending
            # a JSON envelope to an existing event stream.
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            if response_started:
                raise
            response = internal_error_response(request_id)
            await response(scope, receive, send_with_context)
        else:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
        finally:
            reset_request_id(token)
