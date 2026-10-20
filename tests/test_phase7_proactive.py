"""Comprehensive test suite for Phase 7: Proactive Retail Intelligence."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.events.schemas import DomainEventEnvelope
from app.proactive.briefing import (
    DailyBriefingScheduler,
    format_brief_summary,
    resolve_yesterday_ist_date,
)
from app.proactive.dedup import InMemoryAlertDedupStore
from app.proactive.models import (
    AlertSeverity,
    AlertState,
    AlertType,
    NotificationRecord,
)
from app.proactive.notification_store import (
    InMemoryNotificationStore,
    NotificationStore,
)
from app.proactive.stock_monitor import LowStockMonitor, estimate_days_of_stock

STORE_A = "6ad49964d5cb7a1b29d4bb7a"
STORE_B = "6ad49964d5cb7a1b29d4bb7b"
PRODUCT_1 = "6ad4b6206f4697221df5f87a"
PRODUCT_2 = "6ad4b6206f4697221df5f87b"


def make_invoice_released_event(
    store_id: str = STORE_A,
    items: list[dict] | None = None,
    event_id: str = "evt_inv_001",
) -> DomainEventEnvelope:
    return DomainEventEnvelope.model_validate(
        {
            "eventId": event_id,
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": store_id,
            "payload": {
                "invoiceId": "inv_123",
                "invoiceNumber": "INV-202610-001",
                "totalAmount": 500.0,
                "items": items or [],
            },
        }
    )


# ---------------------------------------------------------------------------
# 1. Stock decrease below configured threshold creates correct alert
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stock_decrease_below_threshold_creates_correct_alert() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 8,
            "lowStockThreshold": 10,
        }
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)

    alerts = await monitor.on_invoice_released(event)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.store_id == STORE_A
    assert alert.notification_type == AlertType.LOW_STOCK
    assert alert.severity == AlertSeverity.WARNING
    assert "Low stock: Amul Cheese Slices has 8 units available." in alert.message
    assert "The configured low-stock threshold is 10 units." in alert.message

    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 1
    assert stored[0].id == alert.id


# ---------------------------------------------------------------------------
# 2. Stock above threshold does not create low-stock alert
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stock_above_threshold_does_not_create_alert() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 15,
            "lowStockThreshold": 10,
        }
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)

    alerts = await monitor.on_invoice_released(event)
    assert len(alerts) == 0
    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 0


# ---------------------------------------------------------------------------
# 3. Missing or malformed inventory data does not fabricate quantities
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_or_malformed_inventory_does_not_fabricate() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": None,  # Missing
            "lowStockThreshold": 10,
        },
        {
            "productId": PRODUCT_2,
            "productName": "Butter",
            "availableQuantity": "invalid_number",  # Malformed
            "lowStockThreshold": None,
        },
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)

    alerts = await monitor.on_invoice_released(event)
    assert len(alerts) == 0
    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 0


# ---------------------------------------------------------------------------
# 4. Reliable demand history produces valid stock-coverage estimate
# ---------------------------------------------------------------------------
def test_reliable_demand_history_produces_valid_stock_coverage() -> None:
    # 8 units available, 2 units sold per day -> 4.0 days remaining
    days = estimate_days_of_stock(available_qty=8, daily_sales_velocity=2.0)
    assert days == 4.0

    # 5 units available, 2.5 units sold per day -> 2.0 days remaining
    days = estimate_days_of_stock(available_qty=5, daily_sales_velocity=2.5)
    assert days == 2.0


# ---------------------------------------------------------------------------
# 5. Missing history does not produce misleading days-remaining estimate
# ---------------------------------------------------------------------------
def test_missing_history_does_not_produce_misleading_days_remaining() -> None:
    assert estimate_days_of_stock(available_qty=8, daily_sales_velocity=None) is None
    assert estimate_days_of_stock(available_qty=8, daily_sales_velocity=0) is None
    assert estimate_days_of_stock(available_qty=8, daily_sales_velocity=-1.5) is None
    assert estimate_days_of_stock(available_qty=8, daily_sales_velocity="abc") is None


@pytest.mark.asyncio
async def test_monitor_includes_days_remaining_only_when_velocity_available() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 8,
            "lowStockThreshold": 10,
        }
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)

    # 1. With velocity map: 2 units/day -> est. 4.0 days remaining
    alerts = await monitor.on_invoice_released(
        event, velocity_map={PRODUCT_1: 2.0}
    )
    assert len(alerts) == 1
    assert "est. 4.0 days remaining" in alerts[0].message
    assert alerts[0].data["daysRemaining"] == 4.0


# ---------------------------------------------------------------------------
# 6. Redelivered events do not create duplicate notifications (Cooldown)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_redelivered_events_do_not_duplicate_notifications() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
        cooldown_seconds=86400,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 8,
            "lowStockThreshold": 10,
        }
    ]
    event_1 = make_invoice_released_event(
        store_id=STORE_A, items=items, event_id="evt_001"
    )
    event_2 = make_invoice_released_event(
        store_id=STORE_A, items=items, event_id="evt_002"
    )

    # First delivery: creates alert
    alerts_1 = await monitor.on_invoice_released(event_1)
    assert len(alerts_1) == 1

    # Redelivery / subsequent sale within cooldown: suppressed
    alerts_2 = await monitor.on_invoice_released(event_2)
    assert len(alerts_2) == 0

    # Notification store only has 1 record
    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 1


# ---------------------------------------------------------------------------
# 7. Concurrent workers cannot emit duplicate alerts for same active condition
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_workers_cannot_emit_duplicate_alerts() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
        cooldown_seconds=86400,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 8,
            "lowStockThreshold": 10,
        }
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)

    # 5 concurrent workers process the same condition simultaneously
    results = await asyncio.gather(
        monitor.on_invoice_released(event),
        monitor.on_invoice_released(event),
        monitor.on_invoice_released(event),
        monitor.on_invoice_released(event),
        monitor.on_invoice_released(event),
    )

    total_emitted = sum(len(r) for r in results)
    assert total_emitted == 1

    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 1


# ---------------------------------------------------------------------------
# 8. Recovered stock condition triggers new alert when it becomes low again
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_recovered_stock_triggers_new_alert_when_low_again() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
        cooldown_seconds=86400,
    )

    # 1. Product drops to 8 -> Alert 1 emitted
    item_low = {
        "productId": PRODUCT_1,
        "productName": "Amul Cheese Slices",
        "availableQuantity": 8,
        "lowStockThreshold": 10,
    }
    alerts_1 = await monitor.on_invoice_released(
        make_invoice_released_event(
            store_id=STORE_A, items=[item_low], event_id="evt_01"
        )
    )
    assert len(alerts_1) == 1

    # 2. Stock intake receives 30 units (now 38 available > 10) -> Recovery
    intake_event = DomainEventEnvelope.model_validate(
        {
            "eventId": "evt_intake_01",
            "eventType": "stock.intake",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "payload": {
                "billId": "bill_001",
                "items": [
                    {
                        "productId": PRODUCT_1,
                        "availableQuantity": 38,
                        "lowStockThreshold": 10,
                    }
                ],
            },
        }
    )
    recovered = await monitor.on_stock_intake(intake_event)
    assert PRODUCT_1 in recovered

    state = await dedup.get_state(
        store_id=STORE_A, alert_type=AlertType.LOW_STOCK, entity_id=PRODUCT_1
    )
    assert state["state"] == AlertState.HEALTHY.value

    # 3. Subsequent sales drop it back to 7 units -> Alert 2 emitted immediately!
    item_low_again = {
        "productId": PRODUCT_1,
        "productName": "Amul Cheese Slices",
        "availableQuantity": 7,
        "lowStockThreshold": 10,
    }
    alerts_2 = await monitor.on_invoice_released(
        make_invoice_released_event(
            store_id=STORE_A, items=[item_low_again], event_id="evt_02"
        )
    )
    assert len(alerts_2) == 1
    assert "has 7 units available" in alerts_2[0].message

    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 2


# ---------------------------------------------------------------------------
# 9. Different stores never share alerts or deduplication state
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_different_stores_never_share_alerts_or_dedup_state() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=True,
    )

    item = {
        "productId": PRODUCT_1,
        "productName": "Amul Cheese Slices",
        "availableQuantity": 5,
        "lowStockThreshold": 10,
    }

    # Store A triggers alert
    alerts_a = await monitor.on_invoice_released(
        make_invoice_released_event(store_id=STORE_A, items=[item], event_id="evt_a")
    )
    assert len(alerts_a) == 1
    assert alerts_a[0].store_id == STORE_A

    # Store B triggers alert for same product ID
    alerts_b = await monitor.on_invoice_released(
        make_invoice_released_event(store_id=STORE_B, items=[item], event_id="evt_b")
    )
    assert len(alerts_b) == 1
    assert alerts_b[0].store_id == STORE_B

    # Queries are strictly partitioned
    notifs_a = await notif_store.get_notifications(STORE_A)
    notifs_b = await notif_store.get_notifications(STORE_B)
    assert len(notifs_a) == 1
    assert len(notifs_b) == 1
    assert notifs_a[0].store_id == STORE_A
    assert notifs_b[0].store_id == STORE_B


# ---------------------------------------------------------------------------
# 10. Daily briefing schedule configuration and timezone
# ---------------------------------------------------------------------------
def test_daily_briefing_schedule_configuration_0800_ist() -> None:
    scheduler = DailyBriefingScheduler(
        notification_store=InMemoryNotificationStore(),
        briefing_time="08:00",
        timezone_str="Asia/Kolkata",
    )
    assert scheduler.briefing_time == "08:00"
    assert scheduler.timezone_str == "Asia/Kolkata"

    tz = ZoneInfo("Asia/Kolkata")
    dt = datetime(2026, 10, 21, 8, 0, 0, tzinfo=tz)
    yesterday = resolve_yesterday_ist_date(dt)
    assert yesterday == "2026-10-20"


# ---------------------------------------------------------------------------
# 11. Retries and simultaneous workers cannot duplicate daily briefings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simultaneous_workers_cannot_duplicate_daily_briefings() -> None:
    notif_store = InMemoryNotificationStore()
    scheduler = DailyBriefingScheduler(
        notification_store=notif_store,
        enabled=True,
    )

    mock_data = {
        "sales": {"today": {"totalRevenue": 15000.0, "totalOrders": 25}},
        "stock": {"totals": {"totalSkus": 50, "lowStockItems": 3}},
        "customers": {"totalDues": 4500.0, "customersWithDues": 4},
        "expenses": {
            "amounts": {"todayAmount": 1200.0},
            "counts": {"todayExpenses": 2},
        },
    }

    # 3 workers attempt to compile brief for Store A on 2026-10-20
    results = await asyncio.gather(
        scheduler.compile_brief_for_store(
            STORE_A, date_str="2026-10-20", mock_data=mock_data
        ),
        scheduler.compile_brief_for_store(
            STORE_A, date_str="2026-10-20", mock_data=mock_data
        ),
        scheduler.compile_brief_for_store(
            STORE_A, date_str="2026-10-20", mock_data=mock_data
        ),
    )

    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1
    assert non_none[0].store_id == STORE_A
    assert non_none[0].entity_id == "2026-10-20"

    # Re-running again returns None (idempotent)
    repeat = await scheduler.compile_brief_for_store(
        STORE_A, date_str="2026-10-20", mock_data=mock_data
    )
    assert repeat is None

    stored = await notif_store.get_notifications(STORE_A)
    assert len(stored) == 1


# ---------------------------------------------------------------------------
# 12. Business-day boundaries and reporting windows are correct
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_business_day_boundaries_and_reporting_windows() -> None:
    notif_store = InMemoryNotificationStore()
    scheduler = DailyBriefingScheduler(
        notification_store=notif_store,
        enabled=True,
    )

    mock_data = {
        "sales": {"today": {"totalRevenue": 8000.0, "totalOrders": 12}},
    }
    brief_record = await scheduler.compile_brief_for_store(
        STORE_A, date_str="2026-10-20", mock_data=mock_data
    )
    assert brief_record is not None
    data = brief_record.data
    assert data["date"] == "2026-10-20"
    assert data["coverage"]["window"] == "today"
    assert data["coverage"]["date"] == "2026-10-20"


# ---------------------------------------------------------------------------
# 13. Incomplete insight data is clearly represented
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_incomplete_insight_data_clearly_represented() -> None:
    notif_store = InMemoryNotificationStore()
    scheduler = DailyBriefingScheduler(
        notification_store=notif_store,
        enabled=True,
    )

    # Sales and inventory available, customer dues and expenses unavailable
    mock_data = {
        "sales": {"today": {"totalRevenue": 5000.0, "totalOrders": 10}},
        "stock": {"totals": {"totalSkus": 20, "lowStockItems": 1}},
        "customers": None,  # Unavailable
        "expenses": None,   # Unavailable
    }

    record = await scheduler.compile_brief_for_store(
        STORE_A, date_str="2026-10-20", mock_data=mock_data
    )
    assert record is not None
    brief = record.data

    assert brief["todaySales"]["status"] == "AVAILABLE"
    assert brief["inventoryHealth"]["status"] == "AVAILABLE"
    assert brief["customerReceivables"]["status"] == "UNAVAILABLE"
    assert brief["customerReceivables"]["totalDues"] is None
    assert brief["expenses"]["status"] == "UNAVAILABLE"
    assert brief["expenses"]["totalExpense"] is None
    assert brief["netCashflowStatus"] == "UNAVAILABLE"
    assert brief["coverage"]["is_complete"] is False

    summary = format_brief_summary(brief, "2026-10-20")
    assert "• Receivables: Data unavailable." in summary
    assert "• Expenses: Data unavailable." in summary
    assert "• Sales: ₹5000.00 revenue" in summary


# ---------------------------------------------------------------------------
# 14. Notification delivery failures can be recovered safely
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notification_delivery_failures_can_be_recovered() -> None:
    dedup = InMemoryAlertDedupStore()
    failing_store = AsyncMock(spec=NotificationStore)
    failing_store.save_notification.side_effect = RuntimeError("DB write error")

    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=failing_store,
        enabled=True,
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 8,
            "lowStockThreshold": 10,
        }
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)

    # 1. Attempt fails: exception handled, claim released
    alerts_1 = await monitor.on_invoice_released(event)
    assert len(alerts_1) == 0

    # Claim should be released
    claim_key = f"{STORE_A}:{AlertType.LOW_STOCK.value}:{PRODUCT_1}"
    assert dedup._claims.get(claim_key) is None

    # 2. Subsequent retry with healthy notification store succeeds
    healthy_store = InMemoryNotificationStore()
    monitor._notifications = healthy_store

    alerts_2 = await monitor.on_invoice_released(event)
    assert len(alerts_2) == 1
    assert alerts_2[0].store_id == STORE_A


# ---------------------------------------------------------------------------
# 15. Disabled feature flags prevent new proactive notifications
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_disabled_feature_flags_prevent_notifications() -> None:
    dedup = InMemoryAlertDedupStore()
    notif_store = InMemoryNotificationStore()

    # LowStockMonitor disabled
    monitor = LowStockMonitor(
        dedup_store=dedup,
        notification_store=notif_store,
        enabled=False,  # Disabled
    )

    items = [
        {
            "productId": PRODUCT_1,
            "productName": "Amul Cheese Slices",
            "availableQuantity": 2,
            "lowStockThreshold": 10,
        }
    ]
    event = make_invoice_released_event(store_id=STORE_A, items=items)
    alerts = await monitor.on_invoice_released(event)
    assert len(alerts) == 0
    assert len(await notif_store.get_notifications(STORE_A)) == 0

    # DailyBriefingScheduler disabled
    scheduler = DailyBriefingScheduler(
        notification_store=notif_store,
        enabled=False,  # Disabled
    )
    await scheduler.start()
    assert scheduler._running is False
    assert scheduler._task is None


# ---------------------------------------------------------------------------
# 16. Notification mark-read and retrieval
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notification_store_mark_read_and_filtering() -> None:
    store = InMemoryNotificationStore()
    n1 = NotificationRecord(
        storeId=STORE_A,
        notificationType=AlertType.LOW_STOCK,
        title="Alert 1",
        message="Stock is low",
    )
    n2 = NotificationRecord(
        storeId=STORE_A,
        notificationType=AlertType.DAILY_BRIEF,
        title="Brief 1",
        message="Daily brief",
    )
    await store.save_notification(n1)
    await store.save_notification(n2)

    unread = await store.get_notifications(STORE_A, unread_only=True)
    assert len(unread) == 2

    # Mark n1 read
    marked = await store.mark_read(STORE_A, n1.id)
    assert marked is True

    unread_after = await store.get_notifications(STORE_A, unread_only=True)
    assert len(unread_after) == 1
    assert unread_after[0].id == n2.id
