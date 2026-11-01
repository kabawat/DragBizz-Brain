"""Sales event handler: invalidates store-scoped BI insight caches."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.events.schemas import DomainEventEnvelope, InvoiceReleasedPayload
from app.insights.cache import InsightCache

if TYPE_CHECKING:
    from app.proactive.stock_monitor import LowStockMonitor

logger = logging.getLogger(__name__)


class SalesEventHandler:
    """Handles invoice.released events idempotently."""

    def __init__(
        self,
        insight_cache: InsightCache,
        stock_monitor: LowStockMonitor | None = None,
    ) -> None:
        self._cache = insight_cache
        self._monitor = stock_monitor

    async def handle(self, event: DomainEventEnvelope) -> dict[str, Any]:
        InvoiceReleasedPayload.model_validate(event.payload)

        # Invalidate only this store's insight cache
        invalidated = await self._cache.invalidate_store(event.store_id)
        logger.info(
            "Processed invoice.released %s for store %s (invalidated %d entries)",
            event.event_id,
            event.store_id,
            invalidated,
        )

        alerts = []
        if self._monitor is not None:
            try:
                alerts = await self._monitor.on_invoice_released(event)
            except Exception as exc:
                logger.error(
                    "Error in proactive stock monitor for event %s: %s",
                    event.event_id,
                    exc,
                    exc_info=True,
                )

        return {
            "status": "handled",
            "event_id": event.event_id,
            "store_id": event.store_id,
            "invalidated_entries": invalidated,
            "alerts_emitted": len(alerts),
        }
