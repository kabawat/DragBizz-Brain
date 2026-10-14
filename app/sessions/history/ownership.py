from __future__ import annotations

from typing import Any

from app.core.exceptions import AppError


def assert_owner_memory(
    meta: dict[str, Any], *, user_id: str, store_id: str
) -> None:
    if meta.get("user_id") != user_id or meta.get("store_id") != store_id:
        raise AppError(
            code="SESSION_FORBIDDEN",
            message="Chat session does not belong to this user/store",
            status_code=403,
        )


def assert_owner_doc(doc: dict[str, Any], *, user_id: str, store_id: str) -> None:
    if doc.get("userId") != user_id or doc.get("storeId") != store_id:
        raise AppError(
            code="SESSION_FORBIDDEN",
            message="Chat session does not belong to this user/store",
            status_code=403,
        )


def not_found() -> AppError:
    return AppError(
        code="SESSION_NOT_FOUND",
        message="Chat session not found",
        status_code=404,
    )
