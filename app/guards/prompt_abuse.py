"""Track consecutive blocked prompts and apply a short user/store lockout."""

from __future__ import annotations

import asyncio
import hashlib
import time

from app.core.exceptions import AppError

_KEY_PREFIX = "ai:security:prompt"


class PromptAbuseLimiter:
    """Three consecutive guard/tool-input violations trigger a five-minute lock."""

    def __init__(
        self,
        redis_client=None,
        *,
        threshold: int = 3,
        violation_window_seconds: int = 300,
        lockout_seconds: int = 300,
        clock=time.monotonic,
    ) -> None:
        self._redis = redis_client
        self._threshold = threshold
        self._violation_window = violation_window_seconds
        self._lockout = lockout_seconds
        self._clock = clock
        self._memory: dict[str, tuple[int, float, float]] = {}
        self._lock = asyncio.Lock()

    @property
    def threshold(self) -> int:
        return self._threshold

    async def is_locked(self, *, user_id: str, store_id: str) -> bool:
        strike_key, lock_key = self._keys(user_id, store_id)
        if self._redis is not None:
            try:
                return bool(await self._redis.get(lock_key))
            except Exception as exc:
                raise self._unavailable() from exc
        async with self._lock:
            item = self._memory.get(strike_key)
            if item is None:
                return False
            now = self._clock()
            _, expires_at, locked_until = item
            if now >= expires_at or (locked_until and now >= locked_until):
                self._memory.pop(strike_key, None)
                return False
            return locked_until > now

    async def record_violation(self, *, user_id: str, store_id: str) -> int:
        strike_key, lock_key = self._keys(user_id, store_id)
        if self._redis is not None:
            try:
                count = int(await self._redis.incr(strike_key))
                if count == 1:
                    await self._redis.expire(strike_key, self._violation_window)
                if count >= self._threshold:
                    await self._redis.set(lock_key, "1", ex=self._lockout)
                return count
            except Exception as exc:
                raise self._unavailable() from exc
        async with self._lock:
            now = self._clock()
            count, expires_at, locked_until = self._memory.get(
                strike_key, (0, 0.0, 0.0)
            )
            if now >= expires_at or (locked_until and now >= locked_until):
                count = 0
                locked_until = 0.0
            count += 1
            expires_at = now + self._violation_window
            if count >= self._threshold:
                locked_until = now + self._lockout
            self._memory[strike_key] = (count, expires_at, locked_until)
            return count

    async def clear(self, *, user_id: str, store_id: str) -> None:
        strike_key, lock_key = self._keys(user_id, store_id)
        if self._redis is not None:
            try:
                await self._redis.delete(strike_key, lock_key)
                return
            except Exception as exc:
                raise self._unavailable() from exc
        async with self._lock:
            self._memory.pop(strike_key, None)

    @staticmethod
    def _keys(user_id: str, store_id: str) -> tuple[str, str]:
        scope = hashlib.sha256(f"{user_id}:{store_id}".encode()).hexdigest()
        base = f"{_KEY_PREFIX}:{scope}"
        return f"{base}:strikes", f"{base}:locked"

    @staticmethod
    def _unavailable() -> AppError:
        return AppError(
            code="AI_SECURITY_CONTROLS_UNAVAILABLE",
            message="Chat security controls are temporarily unavailable",
            status_code=503,
        )
