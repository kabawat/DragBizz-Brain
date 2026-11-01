"""Stock event handler: invalidates store-scoped BI insight caches."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.events.schemas import DomainEventEnvelope, StockIntakePayload
from app.insights.cache import InsightCache

if TYPE_CHECKING:
    from app.proactive.stock_monitor import LowStockMonitor

logger = logging.getLogger(__name__)


class StockEventHandler:
    """Handles stock.intake events idempotently."""

    def __init__(
        self,
        insight_cache: InsightCache,
        stock_monitor: LowStockMonitor | None = None,
    ) -> None:
        self._cache = insight_cache
        self._monitor = stock_monitor

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

        recovered: list[str] = []
        if self._monitor is not None:
            try:
                recovered = await self._monitor.on_stock_intake(event)
            except Exception as exc:
                logger.error(
                    "Error in proactive stock intake recovery for event %s: %s",
                    event.event_id,
                    exc,
                    exc_info=True,
                )

        return {
            "status": "handled",
            "event_id": event.event_id,
            "store_id": event.store_id,
            "invalidated_entries": invalidated,
            "stock_recovered": recovered,
        }
