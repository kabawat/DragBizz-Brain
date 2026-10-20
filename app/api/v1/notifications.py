"""Notification endpoints for store-scoped proactive intelligence."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.proactive.notification_store import NotificationStore
from app.schemas.chat import assert_valid_store_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_notification_store(request: Request) -> NotificationStore:
    store = getattr(request.app.state, "notification_store", None)
    if store is None:
        raise AppError(
            code="NOTIFICATION_STORE_UNAVAILABLE",
            message="Notification store is not available",
            status_code=503,
        )
    return store


def _validate_user_store_access(user: dict[str, Any], store_id: str) -> None:
    role = str(user.get("role") or "").upper()
    if role in ("SUPERADMIN", "PLATFORM_ADMIN"):
        return

    # Check store claims if present
    user_stores = user.get("stores")
    if isinstance(user_stores, list) and user_stores:
        str_stores = [str(s) for s in user_stores]
        if store_id in str_stores:
            return
        raise AppError(
            code="FORBIDDEN_STORE_ACCESS",
            message="User does not have access to this store",
            status_code=403,
        )

    user_store_id = user.get("storeId")
    if user_store_id and str(user_store_id) != store_id:
        raise AppError(
            code="FORBIDDEN_STORE_ACCESS",
            message="User does not have access to this store",
            status_code=403,
        )


@router.get("")
async def list_notifications(
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    store_id: Annotated[str, Query(alias="storeId")],
    unread_only: bool = Query(default=False, alias="unreadOnly"),
    limit: int = Query(default=50, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Retrieve proactive alerts and briefings scoped to the caller's store."""
    valid_store_id = assert_valid_store_id(store_id)
    _validate_user_store_access(user, valid_store_id)

    store = _get_notification_store(request)
    records = await store.get_notifications(
        valid_store_id,
        limit=limit,
        skip=skip,
        unread_only=unread_only,
    )
    unread_count = await store.count_unread(valid_store_id)

    return {
        "success": True,
        "storeId": valid_store_id,
        "totalUnread": unread_count,
        "items": [r.model_dump(by_alias=True) for r in records],
    }


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    store_id: Annotated[str, Query(alias="storeId")],
) -> dict[str, Any]:
    """Mark a notification as read within the caller's authorized store."""
    valid_store_id = assert_valid_store_id(store_id)
    _validate_user_store_access(user, valid_store_id)

    store = _get_notification_store(request)
    marked = await store.mark_read(
        store_id=valid_store_id,
        notification_id=notification_id,
    )
    if not marked:
        raise AppError(
            code="NOTIFICATION_NOT_FOUND",
            message="Notification not found or does not belong to store",
            status_code=404,
        )

    return {
        "success": True,
        "id": notification_id,
        "storeId": valid_store_id,
        "read": True,
    }
