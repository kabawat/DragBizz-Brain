"""Stock event handler: invalidates store-scoped BI insight caches."""

from __future__ import annotations

import logging
from typing import Any

from app.events.schemas import DomainEventEnvelope, StockIntakePayload
from app.insights.cache import InsightCache

logger = logging.getLogger(__name__)


class StockEventHandler:
    """Handles stock.intake events idempotently."""

    def __init__(self, insight_cache: InsightCache) -> None:
        self._cache = insight_cache

    async def handle(self, event: DomainEventEnvelope) -> dict[str, Any]:
        StockIntakePayload.model_validate(event.payload)

        # Invalidate only this store's insight cache
        invalidated = await self._cache.invalidate_store(event.store_id)
        logger.info(
            "Processed stock.intake %s for store %s (invalidated %d entries)",
            event.event_id,
            event.store_id,
            invalidated,
        )
        return {
            "status": "handled",
            "event_id": event.event_id,
            "store_id": event.store_id,
            "invalidated_entries": invalidated,
        }
