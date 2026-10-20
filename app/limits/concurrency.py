"""Lease-based concurrency gates (Redis).

Slots expire via TTL so a crashed worker cannot permanently consume capacity.
Release requires the owner token. Redis errors fail closed.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_KEY_PREFIX = "ai:concurrency"

_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


@dataclass(frozen=True)
class Lease:
    kind: str
    user_id: str
    store_id: str
    token: str
    slot: int


class ConcurrencyGate:
    def __init__(
        self,
        redis_client,
        *,
        max_chat: int = 2,
        max_confirm: int = 2,
        lease_seconds: int = 60,
    ) -> None:
        self._redis = redis_client
        self._max_chat = max_chat
        self._max_confirm = max_confirm
        self._lease_seconds = lease_seconds

    async def acquire_chat(self, *, user_id: str, store_id: str) -> Lease:
        return await self._acquire(
            kind="chat",
            user_id=user_id,
            store_id=store_id,
            limit=self._max_chat,
        )

    async def acquire_confirm(self, *, user_id: str, store_id: str) -> Lease:
        return await self._acquire(
            kind="confirm",
            user_id=user_id,
            store_id=store_id,
            limit=self._max_confirm,
        )

    async def release(self, lease: Lease) -> None:
        if lease.slot < 0 or not lease.token:
            return
        key = self._slot_key(lease.kind, lease.user_id, lease.store_id, lease.slot)
        try:
            await self._redis.eval(_RELEASE_LUA, 1, key, lease.token)
        except Exception:
            logger.warning("Concurrency release failed for key %s", key, exc_info=True)

    async def _acquire(
        self,
        *,
        kind: str,
        user_id: str,
        store_id: str,
        limit: int,
    ) -> Lease:
        if limit <= 0:
            # Disabled: return a no-op lease that release ignores.
            return Lease(
                kind=kind,
                user_id=user_id,
                store_id=store_id,
                token="",
                slot=-1,
            )
        token = secrets.token_urlsafe(16)
        try:
            for slot in range(limit):
                key = self._slot_key(kind, user_id, store_id, slot)
                ok = await self._redis.set(key, token, ex=self._lease_seconds, nx=True)
                if ok:
                    return Lease(
                        kind=kind,
                        user_id=user_id,
                        store_id=store_id,
                        token=token,
                        slot=slot,
                    )
        except Exception as exc:
            logger.warning("Concurrency acquire failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Concurrency store unavailable",
                status_code=503,
            ) from exc
        raise AppError(
            code="AI_CONCURRENCY_LIMIT",
            message="Too many active requests for this store. Please wait.",
            status_code=429,
            retry_after=self._lease_seconds,
        )

    @staticmethod
    def _slot_key(kind: str, user_id: str, store_id: str, slot: int) -> str:
        return f"{_KEY_PREFIX}:{kind}:{user_id}:{store_id}:{slot}"


class InMemoryConcurrencyGate:
    """Single-process lease gate for tests and local dev without Redis."""

    def __init__(
        self,
        *,
        max_chat: int = 2,
        max_confirm: int = 2,
        lease_seconds: int = 60,
    ) -> None:
        self._max_chat = max_chat
        self._max_confirm = max_confirm
        self._lease_seconds = lease_seconds
        self._slots: dict[str, tuple[str, float]] = {}

    async def acquire_chat(self, *, user_id: str, store_id: str) -> Lease:
        return await self._acquire("chat", user_id, store_id, self._max_chat)

    async def acquire_confirm(self, *, user_id: str, store_id: str) -> Lease:
        return await self._acquire("confirm", user_id, store_id, self._max_confirm)

    async def release(self, lease: Lease) -> None:
        if lease.slot < 0:
            return
        key = ConcurrencyGate._slot_key(
            lease.kind, lease.user_id, lease.store_id, lease.slot
        )
        current = self._slots.get(key)
        if current is not None and current[0] == lease.token:
            del self._slots[key]

    async def _acquire(
        self, kind: str, user_id: str, store_id: str, limit: int
    ) -> Lease:
        if limit <= 0:
            return Lease(
                kind=kind,
                user_id=user_id,
                store_id=store_id,
                token="",
                slot=-1,
            )
        now = time.monotonic()
        token = secrets.token_urlsafe(16)
        for slot in range(limit):
            key = ConcurrencyGate._slot_key(kind, user_id, store_id, slot)
            entry = self._slots.get(key)
            if entry is None or entry[1] <= now:
                self._slots[key] = (token, now + self._lease_seconds)
                return Lease(
                    kind=kind,
                    user_id=user_id,
                    store_id=store_id,
                    token=token,
                    slot=slot,
                )
        raise AppError(
            code="AI_CONCURRENCY_LIMIT",
            message="Too many active requests for this store. Please wait.",
            status_code=429,
            retry_after=self._lease_seconds,
        )
