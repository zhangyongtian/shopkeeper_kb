from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status


@dataclass(frozen=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = status.HTTP_400_BAD_REQUEST
    details: Any | None = None


def _get_request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    return None


def _error_response(
    *,
    code: str,
    message: str,
    request_id: str | None,
    status_code: int,
    details: Any | None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else {},
            "request_id": request_id or "",
        }
    }
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            code="REQUEST_VALIDATION_FAILED",
            message="Request validation failed",
            request_id=_get_request_id(request),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"errors": exc.errors()},
        )

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            code=exc.code,
            message=exc.message,
            request_id=_get_request_id(request),
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return _error_response(
            code="INTERNAL_SERVER_ERROR",
            message="Internal server error",
            request_id=_get_request_id(request),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={},
        )
