"""Per-tenant (store) daily token/cost counters for hard caps (Phase 7).

AI-only accounting data — no business data. RedisUsageStore survives
restarts and is shared across instances; InMemoryUsageStore is the
single-instance fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_KEY_PREFIX = "ai:usage"
# Keep yesterday's counters around briefly for inspection, then expire.
_REDIS_TTL_SECONDS = 2 * 86_400
# Cost is stored as integer micro-USD so Redis HINCRBY stays atomic.
_MICRO_USD = 1_000_000


def usage_day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class TenantUsage:
    day: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageStore(Protocol):
    async def record(
        self,
        store_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None: ...

    async def get_today(self, store_id: str) -> TenantUsage: ...


class InMemoryUsageStore:
    def __init__(self) -> None:
        self._day = usage_day()
        self._usage: dict[str, TenantUsage] = {}

    async def record(
        self,
        store_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        self._roll_day()
        current = self._usage.get(store_id) or TenantUsage(day=self._day)
        self._usage[store_id] = TenantUsage(
            day=self._day,
            requests=current.requests + 1,
            input_tokens=current.input_tokens + input_tokens,
            output_tokens=current.output_tokens + output_tokens,
            cost_usd=round(current.cost_usd + cost_usd, 8),
        )

    async def get_today(self, store_id: str) -> TenantUsage:
        self._roll_day()
        return self._usage.get(store_id) or TenantUsage(day=self._day)

    def _roll_day(self) -> None:
        today = usage_day()
        if today != self._day:
            self._day = today
            self._usage.clear()


class RedisUsageStore:
    """Backed by any redis.asyncio-compatible client (decode_responses=True)."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def record(
        self,
        store_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        # A Redis outage must not fail a chat that already succeeded.
        try:
            key = self._key(store_id, usage_day())
            await self._redis.hincrby(key, "requests", 1)
            await self._redis.hincrby(key, "input_tokens", input_tokens)
            await self._redis.hincrby(key, "output_tokens", output_tokens)
            await self._redis.hincrby(
                key, "cost_micro_usd", round(cost_usd * _MICRO_USD)
            )
            await self._redis.expire(key, _REDIS_TTL_SECONDS)
        except Exception:
            logger.warning("Usage counter write failed", exc_info=True)

    async def get_today(self, store_id: str) -> TenantUsage:
        day = usage_day()
        # Fail closed: cap checks must not silently disable on Redis outage.
        try:
            raw = await self._redis.hgetall(self._key(store_id, day)) or {}
        except Exception as exc:
            logger.warning("Usage counter read failed", exc_info=True)
            raise AppError(
                code="AI_STORE_UNAVAILABLE",
                message="Usage store unavailable",
                status_code=503,
            ) from exc
        return TenantUsage(
            day=day,
            requests=int(raw.get("requests", 0)),
            input_tokens=int(raw.get("input_tokens", 0)),
            output_tokens=int(raw.get("output_tokens", 0)),
            cost_usd=int(raw.get("cost_micro_usd", 0)) / _MICRO_USD,
        )

    @staticmethod
    def _key(store_id: str, day: str) -> str:
        return f"{_KEY_PREFIX}:{store_id}:{day}"
