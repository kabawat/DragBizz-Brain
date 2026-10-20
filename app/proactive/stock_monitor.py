"""Low-stock depletion monitor and threshold state evaluator."""

from __future__ import annotations

import logging

from app.events.schemas import DomainEventEnvelope
from app.integrations.core_grpc_client import CoreGrpcClient
from app.integrations.retailer_client import RetailerClient, RetailerHttpError
from app.proactive.dedup import AlertDedupStore
from app.proactive.models import (
    AlertSeverity,
    AlertType,
    LowStockAlertData,
    NotificationRecord,
)
from app.proactive.notification_store import NotificationStore

logger = logging.getLogger(__name__)


def estimate_days_of_stock(
    available_qty: float | int,
    daily_sales_velocity: float | int | None,
) -> float | None:
    """Calculate days of stock remaining strictly from reliable velocity.

    Returns None if daily sales velocity is zero, missing, or negative,
    avoiding deceptive or fabricated demand estimates.
    """
    if daily_sales_velocity is None:
        return None
    try:
        velocity = float(daily_sales_velocity)
        qty = float(available_qty)
    except (ValueError, TypeError):
        return None

    if velocity <= 0:
        return None
    if qty <= 0:
        return 0.0
    return round(qty / velocity, 1)


def format_qty(val: float | int) -> str:
    """Format quantity cleanly without trailing zeroes if integer."""
    try:
        f = float(val)
        return str(int(f)) if f.is_integer() else str(f)
    except (ValueError, TypeError):
        return str(val)


class LowStockMonitor:
    """Evaluates stock-changing domain events and emits advisory low-stock alerts."""

    def __init__(
        self,
        *,
        dedup_store: AlertDedupStore,
        notification_store: NotificationStore,
        grpc_client: CoreGrpcClient | None = None,
        retailer_client: RetailerClient | None = None,
        enabled: bool = False,
        cooldown_seconds: int = 86400,
        claim_ttl_seconds: int = 60,
    ) -> None:
        self._dedup = dedup_store
        self._notifications = notification_store
        self._grpc_client = grpc_client
        self._retailer = retailer_client
        self.enabled = enabled
        self.cooldown_seconds = cooldown_seconds
        self.claim_ttl_seconds = claim_ttl_seconds

    async def on_invoice_released(
        self,
        event: DomainEventEnvelope,
        *,
        access_token: str | None = None,
        velocity_map: dict[str, float] | None = None,
    ) -> list[NotificationRecord]:
        """Process invoice.released event to check for stock depletion."""
        if not self.enabled:
            return []

        store_id = event.store_id
        if not store_id:
            logger.warning("Event %s missing store_id", event.event_id)
            return []

        payload = event.payload or {}
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            # If payload doesn't embed items, attempt to inspect affected stock items
            return []

        emitted_alerts: list[NotificationRecord] = []
        v_map = velocity_map or {}

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            product_id = str(
                item.get("productId") or item.get("id") or item.get("_id") or ""
            )
            if not product_id:
                continue

            product_name = str(
                item.get("productName") or item.get("name") or product_id
            )

            # 1. Authoritative available quantity and threshold
            available_qty: float | None = None
            threshold: float | None = None

            raw_avail = item.get("availableQuantity")
            if raw_avail is None and "stock" in item:
                raw_stock = item.get("stock")
                if isinstance(raw_stock, (int, float)) and not isinstance(
                    raw_stock, bool
                ):
                    raw_avail = raw_stock
                elif isinstance(raw_stock, dict):
                    raw_avail = raw_stock.get("availableQuantity") or raw_stock.get(
                        "quantity"
                    )

            if isinstance(raw_avail, (int, float)) and not isinstance(raw_avail, bool):
                available_qty = float(raw_avail)

            raw_thresh = item.get("lowStockThreshold") or item.get("threshold")
            if isinstance(raw_thresh, (int, float)) and not isinstance(
                raw_thresh, bool
            ):
                threshold = float(raw_thresh)

            # If stock info missing in payload, query authoritative Core gRPC or Retailer API
            if available_qty is None or threshold is None:
                if self._grpc_client is not None:
                    try:
                        items = self._grpc_client.get_store_stock_summary(store_id)
                        for it in items:
                            if it.get("product_id") == product_id:
                                if available_qty is None:
                                    available_qty = it.get("available_quantity")
                                if threshold is None:
                                    threshold = it.get("low_stock_threshold")
                                break
                    except Exception as exc:
                        logger.debug("Could not fetch gRPC stock for product %s: %s", product_id, exc)

                if (
                    (available_qty is None or threshold is None)
                    and self._retailer
                    and (access_token or getattr(self._retailer, "_service_secret", None))
                ):
                    try:
                        inv_res = await self._retailer.get_inventory(
                            access_token=access_token,
                            store_id=store_id,
                            product_id=product_id,
                        )
                        inv_body = (
                            inv_res.body.get("data")
                            if isinstance(inv_res.body, dict)
                            else {}
                        )
                        if isinstance(inv_body, dict) and isinstance(
                            inv_body.get("data"), (dict, list)
                        ):
                            inv_body = inv_body["data"]
                        inv_list = (
                            inv_body["inventories"]
                            if isinstance(inv_body, dict)
                            and isinstance(inv_body.get("inventories"), list)
                            else [inv_body]
                            if isinstance(inv_body, dict)
                            else []
                        )
                        if inv_list and isinstance(inv_list[0], dict):
                            inv_doc = inv_list[0]
                            summary = (
                                inv_doc.get("stockSummary")
                                if isinstance(inv_doc.get("stockSummary"), dict)
                                else {}
                            )
                            status_doc = (
                                inv_doc.get("status")
                                if isinstance(inv_doc.get("status"), dict)
                                else {}
                            )

                            if available_qty is None:
                                cand = summary.get("availableQuantity") or inv_doc.get(
                                    "availableQuantity"
                                )
                                if isinstance(cand, (int, float)) and not isinstance(
                                    cand, bool
                                ):
                                    available_qty = float(cand)

                            if threshold is None:
                                cand_t = status_doc.get("lowStockThreshold") or inv_doc.get(
                                    "lowStockThreshold"
                                )
                                if isinstance(cand_t, (int, float)) and not isinstance(
                                    cand_t, bool
                                ):
                                    threshold = float(cand_t)
                    except (RetailerHttpError, Exception) as exc:
                        logger.debug(
                        "Could not fetch live stock for product %s: %s", product_id, exc
                    )

            # If stock/threshold unresolved, strictly do not invent values
            if available_qty is None or threshold is None:
                continue

            # 2. Check and claim with state machine
            should_alert, reason, claim_id = await self._dedup.check_and_claim(
                store_id=store_id,
                alert_type=AlertType.LOW_STOCK,
                entity_id=product_id,
                current_stock=available_qty,
                threshold=threshold,
                cooldown_seconds=self.cooldown_seconds,
                claim_ttl_seconds=self.claim_ttl_seconds,
            )

            if not should_alert or not claim_id:
                logger.debug(
                    "Suppressed low stock alert for store %s product %s: %s",
                    store_id,
                    product_id,
                    reason,
                )
                continue

            # 3. Velocity / days remaining
            daily_velocity = v_map.get(product_id)
            days_remaining = estimate_days_of_stock(available_qty, daily_velocity)

            # 4. Construct deterministic advisory message
            formatted_avail = format_qty(available_qty)
            formatted_thresh = format_qty(threshold)

            if days_remaining is not None:
                msg = (
                    f"Low stock: {product_name} has {formatted_avail} units available "
                    f"(est. {days_remaining} days remaining). "
                    f"The configured low-stock threshold is {formatted_thresh} units."
                )
            else:
                msg = (
                    f"Low stock: {product_name} has {formatted_avail} units available. "
                    f"The configured low-stock threshold is {formatted_thresh} units."
                )

            severity = (
                AlertSeverity.CRITICAL if available_qty <= 0 else AlertSeverity.WARNING
            )
            alert_data = LowStockAlertData(
                productId=product_id,
                productName=product_name,
                sku=item.get("sku"),
                availableQuantity=available_qty,
                threshold=threshold,
                daysRemaining=days_remaining,
                unit=item.get("unit"),
            )

            notification = NotificationRecord(
                storeId=store_id,
                notificationType=AlertType.LOW_STOCK,
                title="Low Stock Alert",
                message=msg,
                severity=severity,
                entityId=product_id,
                data=alert_data.model_dump(by_alias=True),
            )

            # 5. Persist and commit
            try:
                await self._notifications.save_notification(notification)
                await self._dedup.commit_alert(
                    store_id=store_id,
                    alert_type=AlertType.LOW_STOCK,
                    entity_id=product_id,
                    claim_id=claim_id,
                    current_stock=available_qty,
                    threshold=threshold,
                )
                emitted_alerts.append(notification)
                logger.info(
                    "Emitted low-stock alert for store %s product %s "
                    "(qty=%s, threshold=%s)",
                    store_id,
                    product_id,
                    formatted_avail,
                    formatted_thresh,
                )
            except Exception as exc:
                logger.error(
                    "Failed to save notification for store %s product %s; "
                    "releasing claim: %s",
                    store_id,
                    product_id,
                    exc,
                )
                await self._dedup.release_claim(
                    store_id=store_id,
                    alert_type=AlertType.LOW_STOCK,
                    entity_id=product_id,
                    claim_id=claim_id,
                )

        return emitted_alerts

    async def on_stock_intake(
        self,
        event: DomainEventEnvelope,
        *,
        access_token: str | None = None,
    ) -> list[str]:
        """Process stock.intake event to record stock recovery for replenished items."""
        store_id = event.store_id
        if not store_id:
            return []

        payload = event.payload or {}
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return []

        recovered: list[str] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            product_id = str(item.get("productId") or item.get("id") or "")
            if not product_id:
                continue

            available_qty = item.get("availableQuantity")
            threshold = item.get("lowStockThreshold") or item.get("threshold")

            if (
                isinstance(available_qty, (int, float))
                and isinstance(threshold, (int, float))
                and float(available_qty) > float(threshold)
            ):
                await self._dedup.record_recovery(
                    store_id=store_id,
                    alert_type=AlertType.LOW_STOCK,
                    entity_id=product_id,
                    current_stock=float(available_qty),
                )
                recovered.append(product_id)

        return recovered
