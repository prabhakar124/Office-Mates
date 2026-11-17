"""ASGI middleware.

Written as pure ASGI (not ``BaseHTTPMiddleware``) so it does not buffer responses — the chat
endpoint will stream Server-Sent Events through it.
"""

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from officemates.core.errors import PROBLEM_JSON, internal_error_body
from officemates.core.logging import get_logger
from officemates.core.request_context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "x-request-id"
# Accept a caller-supplied id only if it is short and harmless (prevents log injection).
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

log = get_logger("officemates.request")


class RequestContextMiddleware:
    """Assigns a request id, binds it to logs, echoes it in the response, logs each request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, REQUEST_ID_HEADER)
        request_id = (
            incoming if incoming and _SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        )

        token = set_request_id(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            log.exception("unhandled_error", error_type=type(exc).__name__)
            if response_started:  # too late for a clean error body (e.g. mid-stream)
                raise
            body = internal_error_body(str(scope.get("path", "")))
            await send_wrapper(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", PROBLEM_JSON.encode()),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.unbind_contextvars("request_id")
            reset_request_id(token)


class SecurityHeadersMiddleware:
    """Baseline security headers for API responses."""

    _HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-site"),
    )
    # The API serves JSON only, so nothing it returns may load or run anything. The local
    # /docs page is the exception: it needs its own scripts (it is off when deployed).
    _CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._HEADERS)
                if not scope.get("path", "").startswith("/docs"):
                    headers.append(self._CSP)
                if self.hsts:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _header(scope: Scope, name: str) -> str | None:
    target = name.encode()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            try:
                return str(value.decode("latin-1"))
            except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes any byte
                return None
    return None
