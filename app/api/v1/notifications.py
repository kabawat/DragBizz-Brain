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
    # Only signed authentication claims establish store access. A requested
    # storeId query parameter can select among those claims, but cannot grant it.
    claimed: list[str] = []
    stores = user.get("stores")
    if stores is not None and not isinstance(stores, list):
        raise AppError(
            code="STORE_CONTEXT_REQUIRED",
            message="An authorized store context is required",
            status_code=403,
        )
    for entry in stores or []:
        value = (
            entry.get("storeId", entry.get("store_id", entry.get("id")))
            if isinstance(entry, dict)
            else entry
        )
        if not isinstance(value, str):
            raise AppError(
                code="STORE_CONTEXT_INVALID",
                message="Authorized store context is invalid",
                status_code=403,
            )
        try:
            claimed.append(assert_valid_store_id(value))
        except AppError as exc:
            raise AppError(
                code="STORE_CONTEXT_INVALID",
                message="Authorized store context is invalid",
                status_code=403,
            ) from exc

    single_store = user.get("storeId")
    if single_store is not None:
        if not isinstance(single_store, str):
            raise AppError(
                code="STORE_CONTEXT_INVALID",
                message="Authorized store context is invalid",
                status_code=403,
            )
        try:
            claimed.append(assert_valid_store_id(single_store))
        except AppError as exc:
            raise AppError(
                code="STORE_CONTEXT_INVALID",
                message="Authorized store context is invalid",
                status_code=403,
            ) from exc

    if not claimed:
        raise AppError(
            code="STORE_CONTEXT_REQUIRED",
            message="An authorized store context is required",
            status_code=403,
        )
    if store_id not in set(claimed):
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


@router.patch("/read-all")
async def mark_all_notifications_read(
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    store_id: Annotated[str, Query(alias="storeId")],
) -> dict[str, Any]:
    """Mark all notifications read for the authenticated store context."""
    valid_store_id = assert_valid_store_id(store_id)
    _validate_user_store_access(user, valid_store_id)
    store = _get_notification_store(request)
    updated = await store.mark_all_read(valid_store_id)
    return {
        "success": True,
        "storeId": valid_store_id,
        "updated": updated,
        "read": True,
    }
