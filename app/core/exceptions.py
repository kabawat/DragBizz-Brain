import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHttpException

from app.observability.failures import categorize_error_code

logger = logging.getLogger(__name__)


def _record_app_error_metrics(request: Request, exc: "AppError") -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is None:
        return
    metrics.record_failure_category(categorize_error_code(exc.code))
    if exc.code == "AI_RATE_LIMITED":
        metrics.record_rate_limited()
    elif exc.code == "AI_CONCURRENCY_LIMIT":
        metrics.record_concurrency_limited()
    elif exc.code == "AI_REQUEST_BUDGET_EXCEEDED":
        metrics.record_budget_exceeded()
    elif exc.code == "AI_USAGE_CAP_EXCEEDED":
        metrics.record_cap_block()


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        retryable: bool = False,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        # True when the provider never produced a usable completion
        # (timeout, connection failure, or overloaded/5xx).
        self.retryable = retryable
        self.retry_after = retry_after


def _error_payload(request: Request, code: str, message: str) -> dict:
    return {
        "success": False,
        "error": {"code": code, "message": message},
        "requestId": getattr(request.state, "request_id", None),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        _record_app_error_metrics(request, exc)
        headers = None
        if exc.retry_after is not None:
            headers = {"Retry-After": str(exc.retry_after)}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.code, exc.message),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                **_error_payload(
                    request, "VALIDATION_ERROR", "Request validation failed"
                ),
                "details": exc.errors(),
            },
        )

    @app.exception_handler(StarletteHttpException)
    async def handle_http_error(
        request: Request, exc: StarletteHttpException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, "HTTP_ERROR", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled application error",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request, "INTERNAL_ERROR", "An unexpected error occurred"
            ),
        )
