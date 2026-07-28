"""In-process write idempotency cache (AI-only; Redis later)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.schemas.tool import ToolResult

Clock = Callable[[], float]


@dataclass
class _Entry:
    result: ToolResult
    expires_at: float


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

    def get(self, key: str) -> ToolResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            del self._entries[key]
            return None
        entry.expires_at = self._clock() + self._ttl_seconds
        return entry.result.model_copy(deep=True)

    def put(self, key: str, result: ToolResult) -> None:
        if not result.success:
            return
        self._entries[key] = _Entry(
            result=result.model_copy(deep=True),
            expires_at=self._clock() + self._ttl_seconds,
        )


def build_idempotency_key(
    *,
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Stable key for voice retries: session + tool + canonical args."""
    digest = hashlib.sha256(
        _canonical_json(arguments).encode("utf-8")
    ).hexdigest()[:24]
    return f"ai:{session_id}:{tool_name}:{digest}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
