
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.core.exceptions import AppError
from app.idempotency import build_idempotency_key

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

CONFIRMATION_TYPE_INVOICE_RELEASE = "invoice_release"
CONFIRMATION_TYPE_LEDGER_CREDIT = "ledger_credit"
CONFIRMATION_TYPE_LEDGER_DEBIT = "ledger_debit"

ConfirmationStatus = Literal[
    "PENDING",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "UNKNOWN",
    "REJECTED",
]

_KEY_PREFIX = "ai:confirmation"

_CLAIM_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 'ERR:NOT_FOUND'
end
local payload = cjson.decode(raw)
local now = tonumber(ARGV[1])
if now >= tonumber(payload['expires_at']) then
  redis.call('DEL', KEYS[1])
  return 'ERR:EXPIRED'
end
if payload['user_id'] ~= ARGV[2] or payload['store_id'] ~= ARGV[3]
   or payload['session_id'] ~= ARGV[4] then
  return 'ERR:FORBIDDEN'
end
if ARGV[5] ~= '' and payload['draft_id'] ~= ARGV[5] then
  return 'ERR:DRAFT_MISMATCH'
end
local status = payload['status'] or 'PENDING'
if status == 'SUCCEEDED' or status == 'REJECTED' or status == 'FAILED'
   or status == 'EXECUTING' then
  return 'ERR:ALREADY_USED'
end
local key = ARGV[6]
if key ~= '' then
  payload['business_idempotency_key'] = key
elseif not payload['business_idempotency_key']
   or payload['business_idempotency_key'] == '' then
  return 'ERR:MISSING_KEY'
end
payload['status'] = 'EXECUTING'
local remaining = math.max(1, math.floor(tonumber(payload['expires_at']) - now))
redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', remaining)
return 'OK:' .. cjson.encode(payload)
"""

_COMPLETE_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 'ERR:NOT_FOUND'
end
local payload = cjson.decode(raw)
payload['status'] = ARGV[1]
local now = tonumber(ARGV[2])
local remaining = math.max(1, math.floor(tonumber(payload['expires_at']) - now))
redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', remaining)
return 'OK:' .. cjson.encode(payload)
"""


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
    expires_at: float
    status: ConfirmationStatus = "PENDING"
    business_idempotency_key: str | None = None
    consumed: bool = False  # legacy alias: terminal non-PENDING

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

    async def claim(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
        business_idempotency_key: str | None = None,
    ) -> PendingConfirmationRecord: ...

    async def complete(
        self,
        confirmation_id: str,
        *,
        status: ConfirmationStatus,
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


def _business_key(record: PendingConfirmationRecord) -> str:
    return build_idempotency_key(
        session_id=record.session_id,
        tool_name=record.tool_name,
        arguments={
            **record.arguments,
            "_confirmationId": record.confirmation_id,
        },
    )


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
        self._entries: dict[str, _Entry] = {}
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
        async with self._lock:
            record = self._require_active(confirmation_id)
            self._assert_owner(
                record,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
            )
            if record.status in {"SUCCEEDED", "REJECTED", "FAILED", "EXECUTING"}:
                raise AppError(
                    code="CONFIRMATION_REQUIRED",
                    message="Confirmation was already used",
                    status_code=409,
                )
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
            self._assert_owner(
                record,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
            )
            if draft_id is not None and record.draft_id != draft_id:
                raise AppError(
                    code="CONFIRMATION_FORBIDDEN",
                    message="draftId does not match this confirmation",
                    status_code=403,
                )
            if record.status in {"SUCCEEDED", "REJECTED", "FAILED", "EXECUTING"}:
                raise AppError(
                    code="CONFIRMATION_REQUIRED",
                    message="Confirmation was already used",
                    status_code=409,
                )
            # PENDING or UNKNOWN
            key = business_idempotency_key or record.business_idempotency_key
            if not key:
                key = _business_key(record)
            updated = PendingConfirmationRecord(
                confirmation_id=record.confirmation_id,
                user_id=record.user_id,
                store_id=record.store_id,
                session_id=record.session_id,
                type=record.type,
                draft_id=record.draft_id,
                summary=dict(record.summary),
                tool_name=record.tool_name,
                arguments=dict(record.arguments),
                expires_at=record.expires_at,
                status="EXECUTING",
                business_idempotency_key=key,
                consumed=False,
            )
            self._entries[confirmation_id] = _Entry(record=updated)
            return updated

    async def complete(
        self,
        confirmation_id: str,
        *,
        status: ConfirmationStatus,
    ) -> PendingConfirmationRecord:
        async with self._lock:
            entry = self._entries.get(confirmation_id)
            if entry is None:
                raise AppError(
                    code="CONFIRMATION_NOT_FOUND",
                    message="Confirmation not found",
                    status_code=404,
                )
            record = entry.record
            updated = PendingConfirmationRecord(
                confirmation_id=record.confirmation_id,
                user_id=record.user_id,
                store_id=record.store_id,
                session_id=record.session_id,
                type=record.type,
                draft_id=record.draft_id,
                summary=dict(record.summary),
                tool_name=record.tool_name,
                arguments=dict(record.arguments),
                expires_at=record.expires_at,
                status=status,
                business_idempotency_key=record.business_idempotency_key,
                consumed=status in {"SUCCEEDED", "FAILED", "REJECTED"},
            )
            self._entries[confirmation_id] = _Entry(record=updated)
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
            self._assert_owner(
                record,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
            )
            if draft_id is not None and record.draft_id != draft_id:
                raise AppError(
                    code="CONFIRMATION_FORBIDDEN",
                    message="draftId does not match this confirmation",
                    status_code=403,
                )
            if record.status != "PENDING":
                raise AppError(
                    code="CONFIRMATION_REQUIRED",
                    message="Confirmation was already used",
                    status_code=409,
                )
            updated = PendingConfirmationRecord(
                confirmation_id=record.confirmation_id,
                user_id=record.user_id,
                store_id=record.store_id,
                session_id=record.session_id,
                type=record.type,
                draft_id=record.draft_id,
                summary=dict(record.summary),
                tool_name=record.tool_name,
                arguments=dict(record.arguments),
                expires_at=record.expires_at,
                status="REJECTED",
                business_idempotency_key=record.business_idempotency_key,
                consumed=True,
            )
            self._entries[confirmation_id] = _Entry(record=updated)
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
        return entry.record

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
    """Shared confirmations with Lua atomic claim. Fail-closed on Redis errors."""

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
            status="PENDING",
        )
        try:
            await self._redis.set(
                self._key(confirmation_id),
                self._serialize(record),
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
        record = await self._load(confirmation_id)
        self._assert_owner(
            record, user_id=user_id, store_id=store_id, session_id=session_id
        )
        if record.status in {"SUCCEEDED", "REJECTED", "FAILED", "EXECUTING"}:
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
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
        # Ensure a key exists for first claim (PENDING).
        key = business_idempotency_key or ""
        if not key:
            try:
                existing = await self._load(confirmation_id)
                key = existing.business_idempotency_key or _business_key(existing)
            except AppError:
                key = ""
        try:
            result = await self._redis.eval(
                _CLAIM_LUA,
                1,
                self._key(confirmation_id),
                str(time.time()),
                user_id,
                store_id,
                session_id,
                draft_id or "",
                key,
            )
        except Exception as exc:
            logger.warning("Confirmation claim failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Confirmation store unavailable",
                status_code=503,
            ) from exc
        return self._decode_lua(result)

    async def complete(
        self,
        confirmation_id: str,
        *,
        status: ConfirmationStatus,
    ) -> PendingConfirmationRecord:
        try:
            result = await self._redis.eval(
                _COMPLETE_LUA,
                1,
                self._key(confirmation_id),
                status,
                str(time.time()),
            )
        except Exception as exc:
            logger.warning("Confirmation complete failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Confirmation store unavailable",
                status_code=503,
            ) from exc
        return self._decode_lua(result)

    async def reject(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        store_id: str,
        session_id: str,
        draft_id: str | None = None,
    ) -> PendingConfirmationRecord:
        record = await self.get(
            confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
        )
        if draft_id is not None and record.draft_id != draft_id:
            raise AppError(
                code="CONFIRMATION_FORBIDDEN",
                message="draftId does not match this confirmation",
                status_code=403,
            )
        if record.status != "PENDING":
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
        return await self.complete(confirmation_id, status="REJECTED")

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

    async def _load(self, confirmation_id: str) -> PendingConfirmationRecord:
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
        record = self._deserialize(raw)
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
        return record

    def _decode_lua(self, result: Any) -> PendingConfirmationRecord:
        if not isinstance(result, str):
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            )
        if result.startswith("ERR:"):
            err = result[4:]
            if err == "NOT_FOUND":
                raise AppError(
                    code="CONFIRMATION_NOT_FOUND",
                    message="Confirmation not found",
                    status_code=404,
                )
            if err == "EXPIRED":
                raise AppError(
                    code="CONFIRMATION_EXPIRED",
                    message="Confirmation has expired",
                    status_code=410,
                )
            if err in {"FORBIDDEN", "DRAFT_MISMATCH"}:
                raise AppError(
                    code="CONFIRMATION_FORBIDDEN",
                    message=(
                        "draftId does not match this confirmation"
                        if err == "DRAFT_MISMATCH"
                        else "Confirmation does not belong to this user or store"
                    ),
                    status_code=403,
                )
            raise AppError(
                code="CONFIRMATION_REQUIRED",
                message="Confirmation was already used",
                status_code=409,
            )
        if not result.startswith("OK:"):
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            )
        return self._deserialize(result[3:])

    @staticmethod
    def _serialize(record: PendingConfirmationRecord) -> str:
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
                "status": record.status,
                "business_idempotency_key": record.business_idempotency_key,
                "consumed": record.consumed,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _deserialize(raw: str) -> PendingConfirmationRecord:
        try:
            payload = json.loads(raw)
            status = payload.get("status") or (
                "SUCCEEDED" if payload.get("consumed") else "PENDING"
            )
            return PendingConfirmationRecord(
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
                status=status,
                business_idempotency_key=payload.get("business_idempotency_key"),
                consumed=bool(payload.get("consumed", False)),
            )
        except Exception as exc:
            logger.warning("Confirmation payload corrupt", exc_info=True)
            raise AppError(
                code="CONFIRMATION_NOT_FOUND",
                message="Confirmation not found",
                status_code=404,
            ) from exc

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
