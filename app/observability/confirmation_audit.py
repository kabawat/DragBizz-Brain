from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.observability.context import get_request_id
from app.observability.events import CONFIRMATION_LIFECYCLE, emit_event

if TYPE_CHECKING:
    from app.observability.audit_trail import AuditTrail
    from app.observability.metrics import MetricsRegistry

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "UNKNOWN", "REJECTED"})


def audit_confirmation(
    *,
    audit_trail: AuditTrail | None,
    metrics: MetricsRegistry | None,
    confirmation_id: str,
    type: str,
    status: str,
    previous_status: str | None,
    user_id: str,
    store_id: str,
    session_id: str,
    tool: str,
    business_idempotency_key: str | None = None,
) -> None:
    event = {
        "event": CONFIRMATION_LIFECYCLE,
        "confirmationId": confirmation_id,
        "type": type,
        "status": status,
        "previousStatus": previous_status,
        "userId": user_id,
        "storeId": store_id,
        "sessionId": session_id,
        "requestId": get_request_id(),
        "idempotencyKeyPrefix": (
            business_idempotency_key[:40] if business_idempotency_key else None
        ),
        "tool": tool,
    }
    # Drop None values so allowlist validation stays clean.
    cleaned = {key: value for key, value in event.items() if value is not None}
    emit_event(
        CONFIRMATION_LIFECYCLE,
        status=status,
        confirmationId=confirmation_id,
        type=type,
        tool=tool,
    )
    if audit_trail is not None:
        audit_trail.append(cleaned)
    if metrics is not None and status in _TERMINAL:
        metrics.record_confirm(status=status)
