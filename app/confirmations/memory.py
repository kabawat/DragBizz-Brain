from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from app.confirmations.helpers import (
    _assert_draft,
    _assert_owner,
    _assert_unused,
    _business_key,
    _updated_record,
)
from app.confirmations.models import Clock, ConfirmationStatus, PendingConfirmationRecord
from app.core.exceptions import AppError


class InMemoryConfirmationStore:
    """Process-local confirmations with an asyncio lock for atomic claim."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        clock: Clock | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._entries: dict[str, PendingConfirmationRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
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
            status="PENDING",
        )
        self._entries[confirmation_id] = record
        return record

    async def get(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
    ) -> PendingConfirmationRecord:
        async with self._lock:
            record = self._require_active(confirmation_id)
            _assert_owner(
                record,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
            )
            _assert_unused(record)
            return record

    async def claim(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
        business_idempotency_key: str | None = None,
    ) -> PendingConfirmationRecord:
        async with self._lock:
            record = self._require_active(confirmation_id)
            _assert_owner(
                record,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
            )
            _assert_draft(record, draft_id)
            _assert_unused(record)
            # PENDING or UNKNOWN
            key = business_idempotency_key or record.business_idempotency_key
            if not key:
                key = _business_key(record)
            updated = _updated_record(
                record,
                status="EXECUTING",
                business_idempotency_key=key,
            )
            self._entries[confirmation_id] = updated
            return updated

    async def complete(
        self,
        confirmation_id: str,
        *,
        status: ConfirmationStatus,
    ) -> PendingConfirmationRecord:
        async with self._lock:
            record = self._entries.get(confirmation_id)
            if record is None:
                raise AppError(
                    code="CONFIRMATION_NOT_FOUND",
                    message="Confirmation not found",
                    status_code=404,
                )
            updated = _updated_record(
                record,
                status=status,
            )
            self._entries[confirmation_id] = updated
            return updated

    async def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        async with self._lock:
            record = self._require_active(confirmation_id)
            _assert_owner(
                record,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
            )
            _assert_draft(record, draft_id)
            if record.status != "PENDING":
                raise AppError(
                    code="CONFIRMATION_REQUIRED",
                    message="Confirmation was already used",
                    status_code=409,
                )
            updated = _updated_record(
                record,
                status="REJECTED",
            )
            self._entries[confirmation_id] = updated
            return updated

    # Backward-compatible alias used by older call sites / tests.
    async def consume(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        return await self.claim(
            confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            draft_id=draft_id,
        )

    def _require_active(self, confirmation_id: str) -> PendingConfirmationRecord:
        record = self._entries.get(confirmation_id)
        if record is None:
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            )
        if self._clock() >= record.expires_at:
            del self._entries[confirmation_id]
            raise AppError(
                code="CONFIRMATION_EXPIRED",
                message="Confirmation has expired",
                status_code=410,
            )
        return record
