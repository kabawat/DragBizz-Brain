"""Tenant-isolated cache for deterministic business intelligence insight tools.

Key pattern:
    ai:insight:{store_id}:{tool}:{window}
Default TTL:
    900 seconds (15 minutes).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 900
_STORE_ID_RE = re.compile(r"^[a-fA-F0-9]{24}$")


class InsightCache(Protocol):
    async def get(
        self, store_id: str, tool: str, window: str
    ) -> dict[str, Any] | None: ...

    async def set(
        self, store_id: str, tool: str, window: str, value: dict[str, Any]
    ) -> None: ...

    async def delete(self, store_id: str, tool: str, window: str) -> None: ...

    async def invalidate_store(self, store_id: str) -> int: ...


def _format_cache_key(store_id: str, tool: str, window: str) -> str:
    cleaned_store = str(store_id).strip()
    if not cleaned_store:
        raise ValueError("store_id is required for insight caching")
    cleaned_tool = str(tool).strip().lower()
    cleaned_window = str(window).strip().lower()
    return f"ai:insight:{cleaned_store}:{cleaned_tool}:{cleaned_window}"


class NoOpInsightCache:
    """Disabled cache."""

    async def get(
        self, store_id: str, tool: str, window: str
    ) -> dict[str, Any] | None:
        return None

    async def set(
        self, store_id: str, tool: str, window: str, value: dict[str, Any]
    ) -> None:
        return None

    async def delete(self, store_id: str, tool: str, window: str) -> None:
        return None

    async def invalidate_store(self, store_id: str) -> int:
        return 0


class InMemoryInsightCache:
    """In-memory fallback cache with TTL for local testing or absent Redis."""

    def __init__(self, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, str]] = {}

    async def get(
        self, store_id: str, tool: str, window: str
    ) -> dict[str, Any] | None:
        key = _format_cache_key(store_id, tool, window)
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        try:
            return json.loads(payload)
        except Exception:
            self._store.pop(key, None)
            return None

    async def set(
        self, store_id: str, tool: str, window: str, value: dict[str, Any]
    ) -> None:
        key = _format_cache_key(store_id, tool, window)
        expires_at = time.monotonic() + self._ttl_seconds
        payload = json.dumps(value)
        self._store[key] = (expires_at, payload)

    async def delete(self, store_id: str, tool: str, window: str) -> None:
        key = _format_cache_key(store_id, tool, window)
        self._store.pop(key, None)

    async def invalidate_store(self, store_id: str) -> int:
        cleaned_store = str(store_id).strip()
        if not _STORE_ID_RE.match(cleaned_store):
            return 0
        prefix = f"ai:insight:{cleaned_store}:"
        matched_keys = [k for k in self._store if k.startswith(prefix)]
        for k in matched_keys:
            self._store.pop(k, None)
        return len(matched_keys)


class RedisInsightCache:
    """Production Redis cache for insight results."""

    def __init__(
        self, redis_client: Any, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def get(
        self, store_id: str, tool: str, window: str
    ) -> dict[str, Any] | None:
        try:
            key = _format_cache_key(store_id, tool, window)
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.warning(
                "Redis insight cache get failed for store %s, tool %s",
                store_id,
                tool,
                exc_info=True,
            )
            return None

    async def set(
        self, store_id: str, tool: str, window: str, value: dict[str, Any]
    ) -> None:
        try:
            key = _format_cache_key(store_id, tool, window)
            payload = json.dumps(value)
            await self._redis.set(key, payload, ex=self._ttl_seconds)
        except Exception:
            logger.warning(
                "Redis insight cache set failed for store %s, tool %s",
                store_id,
                tool,
                exc_info=True,
            )

    async def delete(self, store_id: str, tool: str, window: str) -> None:
        try:
            key = _format_cache_key(store_id, tool, window)
            await self._redis.delete(key)
        except Exception:
            logger.warning(
                "Redis insight cache delete failed for store %s, tool %s",
                store_id,
                tool,
                exc_info=True,
            )

    async def invalidate_store(self, store_id: str) -> int:
        cleaned_store = str(store_id).strip()
        if not _STORE_ID_RE.match(cleaned_store):
            logger.warning(
                "Invalid store_id format for insight cache invalidation: %s",
                store_id,
            )
            return 0
        match_pattern = f"ai:insight:{cleaned_store}:*"
        deleted = 0
        try:
            keys: list[str] = []
            async for key in self._redis.scan_iter(match=match_pattern, count=100):
                keys.append(key)
            if keys:
                deleted = await self._redis.delete(*keys)
        except Exception:
            logger.warning(
                "Redis insight cache invalidate_store failed for %s",
                store_id,
                exc_info=True,
            )
        return deleted


def build_insight_cache(
    redis_client: Any | None,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> InsightCache:
    """Factory creating RedisInsightCache or InMemoryInsightCache."""
    if ttl_seconds <= 0:
        return NoOpInsightCache()
    if redis_client is not None:
        return RedisInsightCache(redis_client, ttl_seconds=ttl_seconds)
    return InMemoryInsightCache(ttl_seconds=ttl_seconds)
