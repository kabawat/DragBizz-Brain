"""Daily Store Briefing scheduler and compiler at 08:00 Asia/Kolkata."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.insights.store_brief import compile_store_brief
from app.integrations.core_grpc_client import CoreGrpcClient
from app.integrations.retailer_client import RetailerClient
from app.proactive.models import (
    AlertSeverity,
    AlertType,
    NotificationRecord,
)
from app.proactive.notification_store import NotificationStore

logger = logging.getLogger(__name__)

BRIEFING_LOCK_PREFIX = "ai:briefing:lock:"
BRIEFING_DONE_PREFIX = "ai:briefing:done:"


def resolve_yesterday_ist_date(target_now: datetime | None = None) -> str:
    """Return yesterday's YYYY-MM-DD date string in Asia/Kolkata timezone."""
    tz = ZoneInfo("Asia/Kolkata")
    now_ist = target_now.astimezone(tz) if target_now else datetime.now(tz)
    yesterday = now_ist - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def format_brief_summary(brief: dict[str, Any], date_str: str) -> str:
    """Generate a clean, deterministic textual summary of the store brief."""
    sales = brief.get("todaySales", {})
    inv = brief.get("inventoryHealth", {})
    dues = brief.get("customerReceivables", {})
    exp = brief.get("expenses", {})

    lines: list[str] = [f"Daily Store Brief for {date_str}:"]

    if sales.get("status") == "AVAILABLE":
        rev = sales.get("revenue", "0.00")
        orders = sales.get("ordersCount", 0)
        lines.append(f"• Sales: ₹{rev} revenue across {orders} orders.")
    else:
        lines.append("• Sales: Data unavailable.")

    if inv.get("status") == "AVAILABLE":
        skus = inv.get("totalSkus", 0)
        low_stock = inv.get("lowStockCount", 0)
        out_of_stock = inv.get("outOfStockCount", 0)
        if skus is None:
            lines.append("• Inventory: Total SKU count unavailable.")
        else:
            lines.append(
                f"• Inventory: {skus} active SKUs ({low_stock} low-stock, "
                f"{out_of_stock} out-of-stock)."
            )
    else:
        lines.append("• Inventory: Data unavailable.")

    if dues.get("status") == "AVAILABLE":
        pending_amt = dues.get("totalDues", "0.00")
        cust_cnt = dues.get("customersWithDues", 0)
        lines.append(
            f"• Receivables: ₹{pending_amt} pending across {cust_cnt} customers."
        )
    else:
        lines.append("• Receivables: Data unavailable.")

    if exp.get("status") == "AVAILABLE":
        total_exp = exp.get("totalExpense", "0.00")
        exp_cnt = exp.get("expenseCount", 0)
        lines.append(f"• Expenses: ₹{total_exp} recorded ({exp_cnt} entries).")
    else:
        lines.append("• Expenses: Data unavailable.")

    return "\n".join(lines)


class CoreStoreProvider:
    """Fetches active eligible stores from Core via gRPC or RetailerClient."""

    def __init__(
        self,
        grpc_client: CoreGrpcClient | None = None,
        retailer_client: RetailerClient | None = None,
    ) -> None:
        self._grpc_client = grpc_client
        self._retailer = retailer_client

    async def __call__(self) -> list[str]:
        if self._grpc_client is not None:
            try:
                stores: list[str] = []
                seen: set[str] = set()
                for page in range(1, 101):
                    batch = self._grpc_client.get_active_stores(limit=50, page=page)
                    if not batch:
                        break
                    for item in batch:
                        store_id = (
                            item.get("store_id") if isinstance(item, dict) else None
                        )
                        if store_id and store_id not in seen:
                            seen.add(store_id)
                            stores.append(store_id)
                    if len(batch) < 50:
                        break
                if stores:
                    return stores
            except Exception as exc:
                logger.warning("gRPC store discovery failed: %s", exc)

        if not self._retailer:
            return []
        try:
            res = await self._retailer.get_eligible_stores()
            if res.status_code == 200 and isinstance(res.body, dict):
                data = res.body.get("data")
                if isinstance(data, list):
                    return [
                        str(s.get("storeId"))
                        for s in data
                        if isinstance(s, dict) and s.get("storeId")
                    ]
        except Exception as exc:
            logger.warning("Failed to fetch eligible stores from Core: %s", exc)
        return []


class DailyBriefingScheduler:
    """Idempotent scheduled engine compiling 08:00 AM IST store briefings."""

    def __init__(
        self,
        *,
        notification_store: NotificationStore,
        grpc_client: CoreGrpcClient | None = None,
        retailer_client: RetailerClient | None = None,
        redis_client: Any | None = None,
        enabled: bool = False,
        briefing_time: str = "08:00",
        timezone_str: str = "Asia/Kolkata",
        lock_ttl_seconds: int = 300,
    ) -> None:
        self._notifications = notification_store
        self._grpc_client = grpc_client
        self._retailer = retailer_client
        self._redis = redis_client
        self.enabled = enabled
        self.briefing_time = briefing_time
        self.timezone_str = timezone_str
        self.lock_ttl_seconds = lock_ttl_seconds

        self._in_memory_done: set[str] = set()
        self._in_memory_locks: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def _done_key(self, store_id: str, date_str: str) -> str:
        return f"{BRIEFING_DONE_PREFIX}{store_id}:{date_str}"

    def _lock_key(self, store_id: str, date_str: str) -> str:
        return f"{BRIEFING_LOCK_PREFIX}{store_id}:{date_str}"

    async def is_already_completed(self, store_id: str, date_str: str) -> bool:
        if self._redis is not None:
            done = await self._redis.get(self._done_key(store_id, date_str))
            return bool(done)
        return f"{store_id}:{date_str}" in self._in_memory_done

    async def acquire_lock(self, store_id: str, date_str: str, lock_id: str) -> bool:
        if self._redis is not None:
            return bool(
                await self._redis.set(
                    self._lock_key(store_id, date_str),
                    lock_id,
                    nx=True,
                    ex=self.lock_ttl_seconds,
                )
            )
        now = asyncio.get_event_loop().time()
        key = f"{store_id}:{date_str}"
        if key in self._in_memory_locks and now < self._in_memory_locks[key]:
            return False
        self._in_memory_locks[key] = now + self.lock_ttl_seconds
        return True

    async def release_lock(self, store_id: str, date_str: str, lock_id: str) -> None:
        if self._redis is not None:
            key = self._lock_key(store_id, date_str)
            current = await self._redis.get(key)
            if isinstance(current, bytes):
                current = current.decode()
            if current == lock_id:
                await self._redis.delete(key)
        else:
            self._in_memory_locks.pop(f"{store_id}:{date_str}", None)

    async def mark_completed(self, store_id: str, date_str: str) -> None:
        if self._redis is not None:
            await self._redis.set(
                self._done_key(store_id, date_str), "1", ex=86400 * 400
            )
            await self._redis.delete(self._lock_key(store_id, date_str))
        else:
            self._in_memory_done.add(f"{store_id}:{date_str}")
            self._in_memory_locks.pop(f"{store_id}:{date_str}", None)

    async def compile_brief_for_store(
        self,
        store_id: str,
        *,
        access_token: str | None = None,
        date_str: str | None = None,
        mock_data: dict[str, Any] | None = None,
    ) -> NotificationRecord | None:
        """Idempotently compile and stage a daily briefing notification for store_id."""
        effective_date = date_str or resolve_yesterday_ist_date()

        if await self.is_already_completed(store_id, effective_date):
            logger.debug(
                "Daily briefing for store %s date %s already completed",
                store_id,
                effective_date,
            )
            return None

        lock_id = str(uuid.uuid4())
        locked = await self.acquire_lock(store_id, effective_date, lock_id)
        if not locked:
            logger.debug(
                "Daily briefing for store %s date %s locked by another worker",
                store_id,
                effective_date,
            )
            return None

        try:
            sales_payload: dict[str, Any] | None = None
            stock_payload: dict[str, Any] | None = None
            customer_payload: dict[str, Any] | None = None
            expense_payload: dict[str, Any] | None = None
            source_failures: set[str] = set()

            if mock_data:
                sales_payload = mock_data.get("sales")
                stock_payload = mock_data.get("stock")
                customer_payload = mock_data.get("customers")
                expense_payload = mock_data.get("expenses")
            else:
                if self._grpc_client is not None:
                    # 1. Authoritative completed-day summary over gRPC
                    try:
                        daily_summary = self._grpc_client.get_store_daily_summary(
                            store_id=store_id,
                            period_type="COMPLETED_DAY",
                            target_date=effective_date,
                        )
                        if (
                            daily_summary.get("success")
                            and daily_summary.get("revenue") is not None
                            and daily_summary.get("sales_count") is not None
                        ):
                            sales_payload = {
                                "today": {
                                    "totalRevenue": daily_summary["revenue"],
                                    "totalProfit": daily_summary.get("profit"),
                                    "totalOrders": daily_summary["sales_count"],
                                }
                            }
                            source_failures.discard("sales")
                        else:
                            source_failures.add("sales")
                    except Exception as exc:
                        source_failures.add("sales")
                        logger.warning(
                            "gRPC daily summary fetch failed for %s: %s",
                            store_id,
                            exc,
                        )

                    # 2. Authoritative inventory health over gRPC
                    try:
                        stock_items = self._grpc_client.get_store_stock_summary(
                            store_id=store_id
                        )
                        stock_payload = {
                            "lowStockItems": stock_items,
                            "lowStockCount": len(stock_items),
                            "outOfStockCount": sum(
                                1
                                for item in stock_items
                                if item.get("available_quantity", 0) <= 0
                            ),
                        }
                        source_failures.discard("stock")
                    except Exception as exc:
                        source_failures.add("stock")
                        logger.warning(
                            "gRPC stock summary fetch failed for %s: %s",
                            store_id,
                            exc,
                        )

            if self._retailer and (
                access_token or getattr(self._retailer, "_service_secret", None)
            ):
                # Upstream data fetching with individual fallbacks
                if sales_payload is None:
                    try:
                        s_res = await self._retailer.get_revenue(
                            access_token=access_token, store_id=store_id
                        )
                        if s_res.status_code == 200 and isinstance(s_res.body, dict):
                            sales_payload = s_res.body.get("data")
                            if sales_payload is not None:
                                source_failures.discard("sales")
                        if sales_payload is None:
                            source_failures.add("sales")
                    except Exception as exc:
                        source_failures.add("sales")
                        logger.warning("Could not fetch sales for brief: %s", exc)

                if stock_payload is None:
                    try:
                        stk_res = await self._retailer.get_stock(
                            access_token=access_token, store_id=store_id
                        )
                        if stk_res.status_code == 200 and isinstance(
                            stk_res.body, dict
                        ):
                            stock_payload = stk_res.body.get("data")
                            if stock_payload is not None:
                                source_failures.discard("stock")
                        if stock_payload is None:
                            source_failures.add("stock")
                    except Exception as exc:
                        source_failures.add("stock")
                        logger.warning("Could not fetch stock for brief: %s", exc)

                try:
                    c_res = await self._retailer.get_customer_analytics(
                        access_token=access_token, store_id=store_id
                    )
                    if c_res.status_code == 200 and isinstance(c_res.body, dict):
                        customer_payload = c_res.body.get("data")
                    if customer_payload is None:
                        source_failures.add("customerDues")
                except Exception as exc:
                    source_failures.add("customerDues")
                    logger.warning(
                        "Could not fetch customer analytics for brief: %s", exc
                    )

                try:
                    e_res = await self._retailer.get_expense_analytics(
                        access_token=access_token, store_id=store_id
                    )
                    if e_res.status_code == 200 and isinstance(e_res.body, dict):
                        expense_payload = e_res.body.get("data")
                    if expense_payload is None:
                        source_failures.add("expenses")
                except Exception as exc:
                    source_failures.add("expenses")
                    logger.warning(
                        "Could not fetch expense analytics for brief: %s", exc
                    )

            brief = compile_store_brief(
                today_revenue=sales_payload,
                stock_totals=stock_payload,
                customer_totals=customer_payload,
                expense_totals=expense_payload,
                date_str=effective_date,
                reporting_window="completed_business_day",
            )

            msg = format_brief_summary(brief, effective_date)
            notification = NotificationRecord(
                storeId=store_id,
                notificationType=AlertType.DAILY_BRIEF,
                title=f"Daily Store Brief — {effective_date}",
                message=msg,
                severity=AlertSeverity.INFO,
                entityId=effective_date,
                data=brief,
            )

            if source_failures or not any(
                (sales_payload, stock_payload, customer_payload, expense_payload)
            ):
                raise RuntimeError("Briefing source data unavailable; retry required")

            await self._notifications.save_notification(notification)
            await self.mark_completed(store_id, effective_date)
            logger.info(
                "Emitted daily briefing for store %s date %s",
                store_id,
                effective_date,
            )
            return notification

        except Exception as exc:
            logger.error(
                "Error compiling daily brief for store %s: %s; releasing lock",
                store_id,
                exc,
                exc_info=True,
            )
            await self.release_lock(store_id, effective_date, lock_id)
            raise

    async def start(self, store_provider: Any = None) -> None:
        """Start background polling loop for 08:00 AM IST schedule."""
        if not self.enabled or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._schedule_loop(store_provider),
            name="daily_briefing_scheduler",
        )
        logger.info(
            "DailyBriefingScheduler started (schedule=%s, tz=%s)",
            self.briefing_time,
            self.timezone_str,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("DailyBriefingScheduler stopped")

    async def _schedule_loop(self, store_provider: Any = None) -> None:
        """Background periodic check loop."""
        while self._running:
            try:
                tz = ZoneInfo(self.timezone_str)
                now_tz = datetime.now(tz)
                target_hour, target_minute = [
                    int(x) for x in self.briefing_time.split(":")
                ]

                # Catch-up or scheduled trigger:
                # If current time is past or at target time today (e.g. >= 08:00 IST)
                is_time_to_run = (
                    now_tz.hour > target_hour
                    or (now_tz.hour == target_hour and now_tz.minute >= target_minute)
                )

                if is_time_to_run:
                    date_str = resolve_yesterday_ist_date(now_tz)
                    stores = []
                    if callable(store_provider):
                        provided = store_provider()
                        stores = (
                            await provided
                            if inspect.isawaitable(provided)
                            else provided
                        )
                    for store_id in stores:
                        if not await self.is_already_completed(store_id, date_str):
                            try:
                                await self.compile_brief_for_store(
                                    store_id, date_str=date_str
                                )
                            except Exception as e:
                                logger.warning(
                                    "Briefing failed for store %s: %s", store_id, e
                                )
                    # Sleep 60s before next check
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in briefing scheduler loop: %s", e)
                await asyncio.sleep(30)
