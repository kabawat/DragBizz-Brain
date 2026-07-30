"""Runtime provider/model selection, switchable by platform admins.

The selection overrides the env defaults (AI_ACTIVE_PROVIDER /
AI_OPENAI_MODEL) without a restart. RedisModelSelectionStore persists it
across restarts and instances; InMemoryModelSelectionStore is the
single-instance fallback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

_REDIS_KEY = "ai:model_selection"


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    model: str
    updated_by: str
    updated_at: str


class ModelSelectionStore(Protocol):
    async def get(self) -> ModelSelection | None: ...

    async def set(self, selection: ModelSelection) -> None: ...


class InMemoryModelSelectionStore:
    def __init__(self) -> None:
        self._selection: ModelSelection | None = None

    async def get(self) -> ModelSelection | None:
        return self._selection

    async def set(self, selection: ModelSelection) -> None:
        self._selection = selection


class RedisModelSelectionStore:
    """Backed by any redis.asyncio-compatible client (decode_responses=True)."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def get(self) -> ModelSelection | None:
        # Redis outage or a corrupt value must not break chat — fall back
        # to env defaults. Writes (set) DO raise so admins see failures.
        try:
            raw = await self._redis.get(_REDIS_KEY)
        except Exception:
            logger.warning(
                "Model selection read failed; using env defaults",
                exc_info=True,
            )
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return ModelSelection(
                provider=str(payload["provider"]),
                model=str(payload["model"]),
                updated_by=str(payload["updated_by"]),
                updated_at=str(payload["updated_at"]),
            )
        except (ValueError, KeyError, TypeError):
            logger.warning("Persisted model selection is corrupt; ignoring")
            return None

    async def set(self, selection: ModelSelection) -> None:
        await self._redis.set(_REDIS_KEY, json.dumps(asdict(selection)))
