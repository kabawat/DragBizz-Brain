"""Authorization helpers for selecting a store from signed auth claims."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.core.exceptions import AppError
from app.integrations.retailer_client import RetailerHttpError
from app.schemas.chat import assert_valid_store_id


def _forbidden(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=403)


def authorized_store_entry(
    user: dict[str, Any], store_id: str
) -> dict[str, Any] | None:
    """Require the requested store to appear in the verified token claims."""
    claimed: list[dict[str, Any]] = []
    stores = user.get("stores")
    if stores is not None and not isinstance(stores, list):
        raise _forbidden(
            "STORE_CONTEXT_REQUIRED", "An authorized store context is required"
        )

    for entry in stores or []:
        value = (
            entry.get("storeId", entry.get("store_id", entry.get("id")))
            if isinstance(entry, dict)
            else entry
        )
        if not isinstance(value, str):
            raise _forbidden(
                "STORE_CONTEXT_INVALID", "Authorized store context is invalid"
            )
        try:
            normalized = assert_valid_store_id(value)
        except AppError as exc:
            raise _forbidden(
                "STORE_CONTEXT_INVALID", "Authorized store context is invalid"
            ) from exc
        claimed.append(
            {"storeId": normalized, **(entry if isinstance(entry, dict) else {})}
        )

    single_store = user.get("storeId")
    if single_store is not None:
        if not isinstance(single_store, str):
            raise _forbidden(
                "STORE_CONTEXT_INVALID", "Authorized store context is invalid"
            )
        try:
            claimed.append({"storeId": assert_valid_store_id(single_store)})
        except AppError as exc:
            raise _forbidden(
                "STORE_CONTEXT_INVALID", "Authorized store context is invalid"
            ) from exc

    if not claimed:
        raise _forbidden(
            "STORE_CONTEXT_REQUIRED", "An authorized store context is required"
        )
    for entry in claimed:
        if entry["storeId"] == store_id:
            return entry
    raise _forbidden(
        "FORBIDDEN_STORE_ACCESS", "User does not have access to this store"
    )


async def authorize_store_access(
    request: Request, user: dict[str, Any], store_id: str
) -> None:
    """Ask Core to verify store ownership/assignment using the verified token."""
    # Signed store claims, when present, are an additional restriction.
    if user.get("stores") is not None or user.get("storeId") is not None:
        authorized_store_entry(user, store_id)
        return
    if not isinstance(user.get("sub"), str) or not isinstance(user.get("role"), str):
        raise _forbidden(
            "STORE_CONTEXT_REQUIRED", "An authorized store context is required"
        )

    access_token = getattr(request.state, "access_token", None)
    retailer = getattr(request.app.state, "retailer_client", None)
    if not access_token or retailer is None:
        raise AppError(
            code="STORE_AUTHORIZATION_UNAVAILABLE",
            message="Store authorization could not be verified",
            status_code=503,
        )
    try:
        await retailer.verify_store_access(
            access_token=access_token,
            store_id=store_id,
            agency_id=user.get("agencyId"),
        )
    except RetailerHttpError as exc:
        if exc.status_code in {403, 404}:
            raise _forbidden(
                "FORBIDDEN_STORE_ACCESS", "User does not have access to this store"
            ) from exc
        raise AppError(
            code="STORE_AUTHORIZATION_UNAVAILABLE",
            message="Store authorization could not be verified",
            status_code=503,
        ) from exc


def explicit_store_permissions(
    user: dict[str, Any], store_id: str
) -> frozenset[str] | None:
    """Return explicit token permissions, or None when Core remains authority."""
    if user.get("stores") is None and user.get("storeId") is None:
        return None
    entry = authorized_store_entry(user, store_id)
    raw = entry.get("permissions") if entry else None
    # A user-level permission list is safe as a fallback only for a single
    # store claim. With multiple stores it has no tenant binding, so treating
    # it as store-scoped could expose tools in the wrong tenant.
    stores = user.get("stores")
    is_multi_store = isinstance(stores, list) and len(stores) > 1
    if raw is None and not is_multi_store:
        raw = user.get("permissions")
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise _forbidden(
            "STORE_CONTEXT_INVALID", "Authorized store permissions are invalid"
        )
    return frozenset(raw)


def filter_tool_definitions(
    definitions: Any, permissions: frozenset[str]
) -> tuple[Any, ...]:
    """Narrow model-visible tools when signed claims carry explicit permissions."""
    return tuple(
        definition
        for definition in definitions
        if not definition.required_permissions
        or set(definition.required_permissions).issubset(permissions)
    )
