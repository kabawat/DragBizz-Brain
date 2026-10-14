from __future__ import annotations

from dataclasses import replace

from app.confirmations.models import ConfirmationStatus, PendingConfirmationRecord
from app.core.exceptions import AppError
from app.idempotency import build_idempotency_key

_USED_STATUSES = frozenset({"SUCCEEDED", "REJECTED", "FAILED", "EXECUTING"})


def _business_key(record: PendingConfirmationRecord) -> str:
    return build_idempotency_key(
        session_id=record.session_id,
        tool_name=record.tool_name,
        arguments={
            **record.arguments,
            "_confirmationId": record.confirmation_id,
        },
    )


def _assert_owner(
    record: PendingConfirmationRecord,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
) -> None:
    if (
        record.user_id != user_id
        or record.store_id != store_id
        or record.session_id != session_id
    ):
        raise AppError(
            code="CONFIRMATION_FORBIDDEN",
            message="Confirmation does not belong to this user or store",
            status_code=403,
        )


def _assert_draft(record: PendingConfirmationRecord, draft_id: str | None) -> None:
    if draft_id is not None and record.draft_id != draft_id:
        raise AppError(
            code="CONFIRMATION_FORBIDDEN",
            message="draftId does not match this confirmation",
            status_code=403,
        )


def _assert_unused(record: PendingConfirmationRecord) -> None:
    if record.status in _USED_STATUSES:
        raise AppError(
            code="CONFIRMATION_REQUIRED",
            message="Confirmation was already used",
            status_code=409,
        )


def _updated_record(
    record: PendingConfirmationRecord,
    *,
    status: ConfirmationStatus,
    business_idempotency_key: str | None = None,
) -> PendingConfirmationRecord:
    return replace(
        record,
        summary=dict(record.summary),
        arguments=dict(record.arguments),
        status=status,
        business_idempotency_key=(
            record.business_idempotency_key
            if business_idempotency_key is None
            else business_idempotency_key
        ),
        consumed=status in {"SUCCEEDED", "FAILED", "REJECTED"},
    )
