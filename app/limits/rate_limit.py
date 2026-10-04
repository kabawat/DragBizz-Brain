"""Redis fixed-window rate limits.

Boundary bursts near the minute edge (up to ~2x) are an accepted tradeoff
for this phase. Counters are shared across instances. Fail closed on Redis
errors — never silently skip the limit.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_KEY_PREFIX = "ai:ratelimit"


class RateLimiter:
    def __init__(
        self,
        redis_client,
        *,
        chat_per_minute: int = 30,
        confirm_per_minute: int = 20,
    ) -> None:
        self._redis = redis_client
        self._chat_per_minute = chat_per_minute
        self._confirm_per_minute = confirm_per_minute

    async def check_chat(self, *, user_id: str, store_id: str) -> None:
        await self._check(
            kind="chat",
            user_id=user_id,
            store_id=store_id,
            limit=self._chat_per_minute,
        )

    async def check_confirm(self, *, user_id: str, store_id: str) -> None:
        await self._check(
            kind="confirm",
            user_id=user_id,
            store_id=store_id,
            limit=self._confirm_per_minute,
        )

    async def _check(
        self,
        *,
        kind: str,
        user_id: str,
        store_id: str,
        limit: int,
    ) -> None:
        if limit <= 0:
            return
        window = datetime.now(UTC).strftime("%Y%m%d%H%M")
        key = f"{_KEY_PREFIX}:{kind}:{user_id}:{store_id}:{window}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, 70)
        except Exception as exc:
            logger.warning("Rate limit Redis error", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Rate limit store unavailable",
                status_code=503,
            ) from exc
        if count > limit:
            retry_after = max(1, 60 - int(time.time()) % 60)
            raise AppError(
                code="AI_RATE_LIMITED",
                message="Too many requests. Please try again shortly.",
                status_code=429,
                retry_after=retry_after,
            )


class InMemoryRateLimiter:
    """Process-local fixed-window limiter for tests / local dev."""

    def __init__(
        self,
        *,
        chat_per_minute: int = 30,
        confirm_per_minute: int = 20,
    ) -> None:
        self._chat_per_minute = chat_per_minute
        self._confirm_per_minute = confirm_per_minute
        self._counts: dict[str, int] = defaultdict(int)

    async def check_chat(self, *, user_id: str, store_id: str) -> None:
        await self._check("chat", user_id, store_id, self._chat_per_minute)

    async def check_confirm(self, *, user_id: str, store_id: str) -> None:
        await self._check(
            "confirm", user_id, store_id, self._confirm_per_minute
        )

    async def _check(
        self, kind: str, user_id: str, store_id: str, limit: int
    ) -> None:
        if limit <= 0:
            return
        window = datetime.now(UTC).strftime("%Y%m%d%H%M")
        key = f"{kind}:{user_id}:{store_id}:{window}"
        self._counts[key] += 1
        if self._counts[key] > limit:
            raise AppError(
                code="AI_RATE_LIMITED",
                message="Too many requests. Please try again shortly.",
                status_code=429,
                retry_after=max(1, 60 - int(time.time()) % 60),
            )
