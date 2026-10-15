from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from payflow.domain.exceptions import (
    AuthenticationError,
    BadRequestError,
    BusinessRuleError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
    ServiceUnavailableError,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    BadRequestError: status.HTTP_400_BAD_REQUEST,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    BusinessRuleError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    RateLimitExceededError: status.HTTP_429_TOO_MANY_REQUESTS,
    ServiceUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def error_body(
    code: str, message: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def status_for(error: DomainError) -> int:
    for cls in type(error).__mro__:
        if cls in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[cls]
    return status.HTTP_400_BAD_REQUEST


async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
    headers: dict[str, str] = {}
    match exc:
        case AuthenticationError():
            headers["WWW-Authenticate"] = "Bearer"
        case RateLimitExceededError(retry_after_seconds=seconds):
            headers["Retry-After"] = str(seconds)
    return JSONResponse(
        error_body(exc.code, exc.message), status_code=status_for(exc), headers=headers
    )


async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        error_body("validation_error", "request validation failed", details),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    return JSONResponse(
        error_body(code, str(exc.detail)),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def handle_unexpected_error(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        error_body("internal_error", "internal server error"),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(DomainError)(handle_domain_error)
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)
    app.exception_handler(Exception)(handle_unexpected_error)
