"""RFC 9457 problem-detail error envelope and exception handlers.

Every error the API returns is serialized as an RFC 9457 problem detail with a stable
machine-readable ``code`` from :class:`ErrorCode`, so clients branch on the code rather
than parsing human-readable titles.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.schemas.error import ProblemDetail


class ErrorCode(StrEnum):
    """The stable set of machine-readable error codes (spec §Cross-cutting)."""

    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    TOO_MANY_REQUESTS = "too_many_requests"
    INTERNAL_ERROR = "internal_error"


_DEFAULT_TITLES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Validation error",
    ErrorCode.UNAUTHORIZED: "Unauthorized",
    ErrorCode.FORBIDDEN: "Forbidden",
    ErrorCode.NOT_FOUND: "Not found",
    ErrorCode.CONFLICT: "Conflict",
    ErrorCode.TOO_MANY_REQUESTS: "Too many requests",
    ErrorCode.INTERNAL_ERROR: "Internal server error",
}

_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.TOO_MANY_REQUESTS,
}


class ProblemDetailError(Exception):
    """Raise from a route to produce an RFC 9457 problem-detail response."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        detail: str,
        *,
        title: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.title = title
        self.headers = dict(headers) if headers is not None else None
        super().__init__(detail)


def _problem_type(code: ErrorCode) -> str:
    base = get_settings().problems_base_url.rstrip("/")
    return f"{base}/{code.value}"


def _code_for_status(status_code: int) -> ErrorCode:
    return _STATUS_TO_CODE.get(status_code, ErrorCode.INTERNAL_ERROR)


def build_problem_detail(
    status_code: int,
    code: ErrorCode,
    detail: str,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Build the RFC 9457 JSON envelope."""
    return ProblemDetail(
        type=_problem_type(code),
        title=title if title is not None else _DEFAULT_TITLES[code],
        status=status_code,
        detail=detail,
        code=code.value,
    ).model_dump()


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    code = _code_for_status(http_exc.status_code)
    detail = (
        http_exc.detail
        if isinstance(http_exc.detail, str) and http_exc.detail
        else _DEFAULT_TITLES[code]
    )
    return JSONResponse(
        status_code=http_exc.status_code,
        content=build_problem_detail(http_exc.status_code, code, detail),
        headers=http_exc.headers,
    )


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_exc = cast(RequestValidationError, exc)
    errors = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in validation_exc.errors()
    ]
    detail = "; ".join(errors) or "The request is invalid."
    return JSONResponse(
        status_code=422,
        content=build_problem_detail(422, ErrorCode.VALIDATION_ERROR, detail),
    )


async def _problem_detail_error_handler(request: Request, exc: Exception) -> JSONResponse:
    problem_exc = cast(ProblemDetailError, exc)
    return JSONResponse(
        status_code=problem_exc.status_code,
        content=build_problem_detail(
            problem_exc.status_code,
            problem_exc.code,
            problem_exc.detail,
            title=problem_exc.title,
        ),
        headers=problem_exc.headers,
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=build_problem_detail(500, ErrorCode.INTERNAL_ERROR, "An internal error occurred."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register RFC 9457 exception handlers on the given app."""
    app.add_exception_handler(ProblemDetailError, _problem_detail_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
