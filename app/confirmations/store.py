"""Short-lived pending confirmation tokens (InMemory or Redis)."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

CONFIRMATION_TYPE_INVOICE_RELEASE = "invoice_release"
_KEY_PREFIX = "ai:confirmation"


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


class ConfirmationStore(Protocol):
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
    ) -> PendingConfirmationRecord: ...

    async def get(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
    ) -> PendingConfirmationRecord: ...

    async def consume(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord: ...

    async def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord: ...


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
            consumed=False,
        )
        self._entries[confirmation_id] = _Entry(record=record)
        return record

    async def get(
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

    async def consume(
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

    async def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        """Mark pending as used without executing; no retailer side effects."""
        return await self.consume(
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


class RedisConfirmationStore:
    """Shared pending confirmations. Fail-closed — sensitive tokens must
    not silently disappear or double-consume across instances."""

    def __init__(self, redis_client, *, ttl_seconds: int = 300) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

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
        expires_at = time.time() + self._ttl_seconds
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
        try:
            await self._redis.set(
                self._key(confirmation_id),
                self._serialize(record, consumed=False),
                ex=self._ttl_seconds,
            )
        except Exception as exc:
            logger.warning("Confirmation create failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Confirmation store unavailable",
                status_code=503,
            ) from exc
        return record

    async def get(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
    ) -> PendingConfirmationRecord:
        record, consumed = await self._load(confirmation_id)
        self._assert_owner(
            record, user_id=user_id, store_id=store_id, session_id=session_id
        )
        if consumed:
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
        return record

    async def consume(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        record, consumed = await self._load(confirmation_id)
        self._assert_owner(
            record, user_id=user_id, store_id=store_id, session_id=session_id
        )
        if draft_id is not None and record.draft_id != draft_id:
            raise AppError(
                code="CONFIRMATION_FORBIDDEN",
                message="draftId does not match this confirmation",
                status_code=403,
            )
        if consumed:
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
        remaining = max(1, int(record.expires_at - time.time()))
        try:
            await self._redis.set(
                self._key(confirmation_id),
                self._serialize(record, consumed=True),
                ex=remaining,
            )
        except Exception as exc:
            logger.warning("Confirmation consume failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Confirmation store unavailable",
                status_code=503,
            ) from exc
        return record

    async def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        return await self.consume(
            confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            draft_id=draft_id,
        )

    async def _load(
        self, confirmation_id: str
    ) -> tuple[PendingConfirmationRecord, bool]:
        try:
            raw = await self._redis.get(self._key(confirmation_id))
        except Exception as exc:
            logger.warning("Confirmation read failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Confirmation store unavailable",
                status_code=503,
            ) from exc
        if raw is None:
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            )
        try:
            payload = json.loads(raw)
            record = PendingConfirmationRecord(
                confirmation_id=payload["confirmation_id"],
                user_id=payload["user_id"],
                store_id=payload["store_id"],
                session_id=payload["session_id"],
                type=payload["type"],
                draft_id=payload["draft_id"],
                summary=dict(payload.get("summary") or {}),
                tool_name=payload["tool_name"],
                arguments=dict(payload.get("arguments") or {}),
                expires_at=float(payload["expires_at"]),
                consumed=bool(payload.get("consumed", False)),
            )
            consumed = bool(payload.get("consumed", False))
        except Exception as exc:
            logger.warning("Confirmation payload corrupt", exc_info=True)
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            ) from exc
        if time.time() >= record.expires_at:
            try:
                await self._redis.delete(self._key(confirmation_id))
            except Exception:
                logger.warning("Confirmation delete-on-expiry failed", exc_info=True)
            raise AppError(
                code="CONFIRMATION_EXPIRED",
                message="Confirmation has expired",
                status_code=410,
            )
        return record, consumed

    @staticmethod
    def _serialize(record: PendingConfirmationRecord, *, consumed: bool) -> str:
        return json.dumps(
            {
                "confirmation_id": record.confirmation_id,
                "user_id": record.user_id,
                "store_id": record.store_id,
                "session_id": record.session_id,
                "type": record.type,
                "draft_id": record.draft_id,
                "summary": record.summary,
                "tool_name": record.tool_name,
                "arguments": record.arguments,
                "expires_at": record.expires_at,
                "consumed": consumed,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _key(confirmation_id: str) -> str:
        return f"{_KEY_PREFIX}:{confirmation_id}"

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
