"""Application error types and their HTTP mapping.

Handlers return a stable envelope so the dashboard can render failures
consistently:  {"error": {"code": ..., "message": ..., "request_id": ...}}
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_ctx

log = get_logger("errors")


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"


class PermissionError_(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class IntegrationError(AppError):
    """An external platform API rejected or failed the call."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "integration_error"


def _envelope(code: str, message: str, extra: dict | None = None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": request_id_ctx.get()}}
    if extra:
        body["error"]["details"] = extra
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.status_code, _envelope(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            _envelope("validation_error", "Request body failed validation.",
                      {"fields": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return a generic message: never leak internals.
        log.exception("unhandled_error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            _envelope("internal_error", "Something went wrong on our side."),
        )
