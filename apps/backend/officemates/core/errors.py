"""RFC 9457 Problem Details error handling.

Every error leaving the API has the same JSON shape and carries the ``request_id`` so a user
report can be matched to logs and traces. Unexpected exceptions never leak internals.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from officemates.core.request_context import get_request_id

PROBLEM_JSON = "application/problem+json"
PROBLEM_TYPE_BASE = "https://officemates.local/problems/"


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


class AppError(Exception):
    """Base class for expected, client-facing errors raised by our code."""

    status: int = HTTPStatus.BAD_REQUEST
    code: str = "bad-request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class NotFoundError(AppError):
    status = HTTPStatus.NOT_FOUND
    code = "not-found"
    title = "Resource not found"


class PermissionDeniedError(AppError):
    status = HTTPStatus.FORBIDDEN
    code = "permission-denied"
    title = "Permission denied"


class ConflictError(AppError):
    status = HTTPStatus.CONFLICT
    code = "conflict"
    title = "Conflict"


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        type=f"{PROBLEM_TYPE_BASE}{code}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        request_id=get_request_id(),
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - narrowing for the type checker
    return _problem_response(
        request, status=int(exc.status), code=exc.code, title=exc.title, detail=exc.detail
    )


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    status = HTTPStatus(exc.status_code)
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != status.phrase else None
    return _problem_response(
        request,
        status=status.value,
        code=status.phrase.lower().replace(" ", "-"),
        title=status.phrase,
        detail=detail,
        headers=getattr(exc, "headers", None),
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]  # input values deliberately omitted: they may contain secrets or PII
    return _problem_response(
        request,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="validation-error",
        title="Request validation failed",
        errors=errors,
    )


def internal_error_body(path: str) -> bytes:
    """Body for unexpected errors. Built by ``RequestContextMiddleware`` (not an exception
    handler) because Starlette runs catch-all handlers *outside* user middleware, where the
    request id is no longer available."""
    return (
        ProblemDetail(
            type=f"{PROBLEM_TYPE_BASE}internal-error",
            title="Internal server error",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Quote the request_id when reporting it.",
            instance=path,
            request_id=get_request_id(),
        )
        .model_dump_json(exclude_none=True)
        .encode()
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
