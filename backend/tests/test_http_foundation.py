import json
import logging
import re
import sys
from collections.abc import AsyncIterator, Mapping

import httpx
import pytest
from fastapi import HTTPException, Query
from starlette.responses import StreamingResponse

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import JsonFormatter, configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.request_context import REQUEST_ID_HEADER
from app.main import create_app

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def make_app():
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )

    @app.get("/test/validated")
    async def validated(limit: int = Query(ge=1, le=10)) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/test/app-error")
    async def expected_error() -> None:
        raise AppError(
            code="demo_conflict",
            message="演示资源发生冲突。",
            status_code=409,
            details={"field": "name"},
        )

    @app.get("/test/unexpected")
    async def unexpected_error() -> None:
        raise RuntimeError("internal implementation detail")

    @app.get("/test/http-500")
    async def unsafe_http_error() -> None:
        raise HTTPException(
            status_code=500,
            detail="database_url=postgres://user:password@db/internal",
        )

    @app.get("/test/stream")
    async def stream() -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            yield "data: first\n\n"
            yield "data: second\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def test_third_party_http_info_logs_are_suppressed() -> None:
    configure_logging("INFO")

    assert logging.getLogger("httpx").isEnabledFor(logging.INFO) is False
    assert logging.getLogger("httpcore").isEnabledFor(logging.INFO) is False


async def request(
    path: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


async def test_request_id_is_generated_and_returned() -> None:
    response = await request("/test/validated?limit=1")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 200
    assert _REQUEST_ID_PATTERN.fullmatch(request_id)


async def test_safe_client_request_id_is_preserved() -> None:
    response = await request(
        "/test/validated?limit=1",
        headers={REQUEST_ID_HEADER: "frontend-demo_001"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "frontend-demo_001"


async def test_unsafe_client_request_id_is_replaced() -> None:
    response = await request(
        "/test/validated?limit=1",
        headers={REQUEST_ID_HEADER: "invalid request id with spaces"},
    )

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id != "invalid request id with spaces"
    assert _REQUEST_ID_PATTERN.fullmatch(request_id)


async def test_validation_error_uses_uniform_contract() -> None:
    response = await request("/test/validated?limit=0")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "请求参数校验失败。",
            "details": [
                {
                    "field": "query.limit",
                    "message": "Input should be greater than or equal to 1",
                    "type": "greater_than_equal",
                }
            ],
        },
        "request_id": request_id,
    }


async def test_http_errors_use_uniform_contract_and_keep_headers() -> None:
    response = await request("/test/validated", method="POST")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method Not Allowed",
        },
        "request_id": request_id,
    }


async def test_not_found_uses_uniform_contract() -> None:
    response = await request("/missing-route")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
        },
        "request_id": request_id,
    }


async def test_application_error_keeps_public_details() -> None:
    response = await request("/test/app-error")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "demo_conflict",
            "message": "演示资源发生冲突。",
            "details": {"field": "name"},
        },
        "request_id": request_id,
    }


async def test_unexpected_error_is_hidden_from_client() -> None:
    response = await request("/test/unexpected")

    request_id = response.headers[REQUEST_ID_HEADER]
    body = response.json()
    assert response.status_code == 500
    assert body == {
        "error": {
            "code": "internal_server_error",
            "message": "服务器处理请求时发生错误。",
        },
        "request_id": request_id,
    }
    assert "internal implementation detail" not in response.text
    assert "Traceback" not in response.text


async def test_http_5xx_detail_is_hidden_from_client() -> None:
    response = await request("/test/http-500")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "服务器处理请求时发生错误。",
        },
        "request_id": request_id,
    }
    assert "database_url" not in response.text
    assert "password" not in response.text


async def test_streaming_response_is_not_buffered_or_rewritten() -> None:
    response = await request("/test/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "data: first\n\ndata: second\n\n"
    assert _REQUEST_ID_PATTERN.fullmatch(response.headers[REQUEST_ID_HEADER])


def test_json_formatter_redacts_common_secret_patterns() -> None:
    try:
        raise RuntimeError(
            "api_key=super-secret postgres://demo:db-password@localhost/app "
            "Authorization: Bearer example-token"
        )
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.http",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="token=message-secret",
        args=(),
        exc_info=exc_info,
    )
    rendered = JsonFormatter().format(record)

    assert "super-secret" not in rendered
    assert "db-password" not in rendered
    assert "example-token" not in rendered
    assert "message-secret" not in rendered
    assert rendered.count("[REDACTED]") >= 4
    assert "RuntimeError" in rendered


def test_json_formatter_emits_parseable_structured_log() -> None:
    record = logging.LogRecord(
        name="app.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "test-log-001"
    record.method = "GET"
    record.path = "/api/v1/health"
    record.status_code = 200
    record.duration_ms = 1.25

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.http"
    assert payload["message"] == "request_completed"
    assert payload["request_id"] == "test-log-001"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/health"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.25
    assert payload["timestamp"].endswith("+00:00")

async def test_middleware_emits_one_structured_access_record() -> None:
    app = make_app()
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    access_logger = logging.getLogger("app.http")
    original_level = access_logger.level
    handler = CaptureHandler()
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(handler)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/test/validated?limit=1",
                headers={REQUEST_ID_HEADER: "access-log-001"},
            )
    finally:
        access_logger.removeHandler(handler)
        access_logger.setLevel(original_level)

    records = [record for record in captured if record.getMessage() == "request_completed"]
    assert response.status_code == 200
    assert len(records) == 1
    assert getattr(records[0], "request_id") == "access-log-001"
    assert getattr(records[0], "method") == "GET"
    assert getattr(records[0], "path") == "/test/validated"
    assert getattr(records[0], "status_code") == 200
    assert getattr(records[0], "duration_ms") >= 0

async def test_stream_failure_after_response_start_is_not_rewritten_as_json() -> None:
    messages: list[dict] = []
    captured: list[logging.LogRecord] = []

    async def failing_stream(scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"data: before\n\n",
                "more_body": True,
            }
        )
        raise RuntimeError("stream failed")

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    access_logger = logging.getLogger("app.http")
    handler = CaptureHandler()
    access_logger.addHandler(handler)
    try:
        middleware = RequestContextMiddleware(failing_stream)
        with pytest.raises(RuntimeError, match="stream failed"):
            await middleware(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/test/failing-stream",
                    "raw_path": b"/test/failing-stream",
                    "query_string": b"",
                    "headers": [],
                    "client": ("127.0.0.1", 12345),
                    "server": ("test", 80),
                    "state": {},
                },
                receive,
                send,
            )
    finally:
        access_logger.removeHandler(handler)

    assert [message["type"] for message in messages] == [
        "http.response.start",
        "http.response.body",
    ]
    assert messages[1]["body"] == b"data: before\n\n"
    assert b"application/json" not in dict(messages[0]["headers"]).values()
    assert any(key.lower() == b"x-request-id" for key, _ in messages[0]["headers"])
    assert [record.getMessage() for record in captured] == ["request_failed"]
