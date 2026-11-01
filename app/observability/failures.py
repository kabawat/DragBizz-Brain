"""Map AppError codes to stable FailureCategory for metrics/logs."""

from __future__ import annotations

from typing import Literal

FailureCategory = Literal[
    "auth",
    "validation",
    "rate_limit",
    "budget",
    "concurrency",
    "provider",
    "retailer",
    "store",
    "confirmation",
    "rag",
    "internal",
]

_CODE_CATEGORY: dict[str, FailureCategory] = {
    "AUTH_MISSING": "auth",
    "AUTH_EXPIRED": "auth",
    "AUTH_INVALID": "auth",
    "ADMIN_FORBIDDEN": "auth",
    "TOOL_UNAUTHORIZED": "auth",
    "SESSION_FORBIDDEN": "auth",
    "VALIDATION_ERROR": "validation",
    "STORE_ID_REQUIRED": "validation",
    "STORE_ID_INVALID": "validation",
    "TOOL_ARGS_INVALID": "validation",
    "TOOL_NOT_ALLOWED": "validation",
    "TOOL_NOT_EXECUTABLE": "validation",
    "ADMIN_PROVIDER_UNKNOWN": "validation",
    "ADMIN_MODEL_NOT_ALLOWED": "validation",
    "AI_RATE_LIMITED": "rate_limit",
    "AI_USAGE_CAP_EXCEEDED": "budget",
    "AI_REQUEST_BUDGET_EXCEEDED": "budget",
    "AI_CONCURRENCY_LIMIT": "concurrency",
    "AI_PROVIDER_NOT_CONFIGURED": "provider",
    "AI_PROVIDER_ERROR": "provider",
    "AI_DEPENDENCY_UNAVAILABLE": "provider",
    "RETAILER_TIMEOUT": "retailer",
    "RETAILER_UNAVAILABLE": "retailer",
    "RETAILER_ERROR": "retailer",
    "AI_STORE_UNAVAILABLE": "store",
    "CONFIRMATION_REQUIRED": "confirmation",
    "CONFIRMATION_NOT_FOUND": "confirmation",
    "CONFIRMATION_EXPIRED": "confirmation",
    "CONFIRMATION_FORBIDDEN": "confirmation",
    "RAG_UNAVAILABLE": "rag",
}


def categorize_error_code(code: str | None) -> FailureCategory:
    if not code:
        return "internal"
    return _CODE_CATEGORY.get(code, "internal")
