"""AI-only write idempotency cache (InMemory or Redis)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.exceptions import AppError
from app.schemas.tool import ToolResult

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

_KEY_PREFIX = "ai:idempotency"


@dataclass
class _Entry:
    result: ToolResult
    expires_at: float


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> ToolResult | None: ...

    async def put(self, key: str, result: ToolResult) -> None: ...


class InMemoryIdempotencyStore:
    """Caches successful write ToolResults by deterministic key + sliding TTL."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 86_400,
        clock: Clock | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._entries: dict[str, _Entry] = {}

    async def get(self, key: str) -> ToolResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            del self._entries[key]
            return None
        entry.expires_at = self._clock() + self._ttl_seconds
        return entry.result.model_copy(deep=True)

    async def put(self, key: str, result: ToolResult) -> None:
        if not result.success:
            return
        self._entries[key] = _Entry(
            result=result.model_copy(deep=True),
            expires_at=self._clock() + self._ttl_seconds,
        )


class RedisIdempotencyStore:
    """Shared write-result cache. Fail-closed on Redis errors so a miss
    during outage cannot double-POST to retailer."""

    def __init__(self, redis_client, *, ttl_seconds: int = 86_400) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def get(self, key: str) -> ToolResult | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            logger.warning("Idempotency cache read failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Idempotency store unavailable",
                status_code=503,
            ) from exc
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            result = ToolResult.model_validate(payload)
        except Exception:
            logger.warning("Idempotency cache corrupt for key=%s", key)
            return None
        try:
            await self._redis.expire(key, self._ttl_seconds)
        except Exception as exc:
            logger.warning("Idempotency TTL refresh failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Idempotency store unavailable",
                status_code=503,
            ) from exc
        return result

    async def put(self, key: str, result: ToolResult) -> None:
        if not result.success:
            return
        try:
            await self._redis.set(
                key,
                json.dumps(result.model_dump(), ensure_ascii=False),
                ex=self._ttl_seconds,
            )
        except Exception as exc:
            logger.warning("Idempotency cache write failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Idempotency store unavailable",
                status_code=503,
            ) from exc


def build_idempotency_key(
    *,
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Stable Redis/in-memory key: session + tool + canonical args."""
    digest = hashlib.sha256(_canonical_json(arguments).encode("utf-8")).hexdigest()[:24]
    return f"{_KEY_PREFIX}:{session_id}:{tool_name}:{digest}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
