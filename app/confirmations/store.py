"""Short-lived pending confirmation tokens (AI-only; Redis later)."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import AppError

Clock = Callable[[], float]

CONFIRMATION_TYPE_INVOICE_RELEASE = "invoice_release"


@dataclass(frozen=True)
class PendingConfirmationRecord:
    confirmation_id: str
    user_id: str
    store_id: str
    session_id: str
    type: str
    draft_id: str
    summary: dict[str, Any]
    tool_name: str
    arguments: dict[str, Any]
    expires_at: float  # wall-clock epoch seconds
    consumed: bool = False

    def to_public(self) -> dict[str, Any]:
        return {
            "confirmationId": self.confirmation_id,
            "type": self.type,
            "draftId": self.draft_id,
            "summary": dict(self.summary),
            "expiresAt": datetime.fromtimestamp(
                self.expires_at, tz=UTC
            ).isoformat().replace("+00:00", "Z"),
        }


@dataclass
class _Entry:
    record: PendingConfirmationRecord
    # Mutable consumed flag kept on the entry so frozen record can be replaced.
    consumed: bool = False


class InMemoryConfirmationStore:
    """Process-local pending confirmations with absolute TTL + ownership bind."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        clock: Clock | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._entries: dict[str, _Entry] = {}

    def create(
        self,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        type: str,
        draft_id: str,
        summary: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PendingConfirmationRecord:
        confirmation_id = secrets.token_urlsafe(24)
        expires_at = self._clock() + self._ttl_seconds
        record = PendingConfirmationRecord(
            confirmation_id=confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            type=type,
            draft_id=draft_id,
            summary=dict(summary),
            tool_name=tool_name,
            arguments=dict(arguments),
            expires_at=expires_at,
            consumed=False,
        )
        self._entries[confirmation_id] = _Entry(record=record)
        return record

    def get(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
    ) -> PendingConfirmationRecord:
        entry = self._require_active(confirmation_id)
        self._assert_owner(
            entry.record,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
        )
        if entry.consumed:
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
        return entry.record

    def consume(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        entry = self._require_active(confirmation_id)
        self._assert_owner(
            entry.record,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
        )
        if draft_id is not None and entry.record.draft_id != draft_id:
            raise AppError(
                code="CONFIRMATION_FORBIDDEN",
                message="draftId does not match this confirmation",
                status_code=403,
            )
        if entry.consumed:
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
        entry.consumed = True
        return entry.record

    def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        """Mark pending as used without executing; no retailer side effects."""
        return self.consume(
            confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            draft_id=draft_id,
        )

    def _require_active(self, confirmation_id: str) -> _Entry:
        entry = self._entries.get(confirmation_id)
        if entry is None:
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            )
        if self._clock() >= entry.record.expires_at:
            del self._entries[confirmation_id]
            raise AppError(
                code="CONFIRMATION_EXPIRED",
                message="Confirmation has expired",
                status_code=410,
            )
        return entry

    @staticmethod
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
