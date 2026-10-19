from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from app.confirmations.helpers import (
    _assert_owner,
    _assert_unused,
    _business_key,
)
from app.confirmations.models import ConfirmationStatus, PendingConfirmationRecord
from app.confirmations.redis_scripts import _CLAIM_LUA, _COMPLETE_LUA, _REJECT_LUA
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)
_KEY_PREFIX = "ai:confirmation"


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
        _assert_owner(
            record, user_id=user_id, store_id=store_id, session_id=session_id
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
        try:
            result = await self._redis.eval(
                _REJECT_LUA,
                1,
                self._key(confirmation_id),
                str(time.time()),
                user_id,
                store_id,
                session_id,
                draft_id or "",
            )
        except Exception as exc:
            logger.warning("Confirmation reject failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Confirmation store unavailable",
                status_code=503,
            ) from exc
        return self._decode_lua(result)

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
