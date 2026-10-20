"""Proactive Retail Intelligence module: low-stock monitoring and daily briefings."""

from app.proactive.briefing import (
    CoreStoreProvider,
    DailyBriefingScheduler,
    format_brief_summary,
    resolve_yesterday_ist_date,
)
from app.proactive.dedup import (
    AlertDedupStore,
    InMemoryAlertDedupStore,
    RedisAlertDedupStore,
)
from app.proactive.models import (
    AlertSeverity,
    AlertState,
    AlertType,
    LowStockAlertData,
    NotificationRecord,
)
from app.proactive.notification_store import (
    InMemoryNotificationStore,
    MongoNotificationStore,
    NotificationStore,
)
from app.proactive.stock_monitor import LowStockMonitor, estimate_days_of_stock

__all__ = [
    "AlertDedupStore",
    "AlertSeverity",
    "AlertState",
    "AlertType",
    "DailyBriefingScheduler",
    "InMemoryAlertDedupStore",
    "InMemoryNotificationStore",
    "LowStockAlertData",
    "LowStockMonitor",
    "MongoNotificationStore",
    "NotificationRecord",
    "NotificationStore",
    "RedisAlertDedupStore",
    "estimate_days_of_stock",
    "format_brief_summary",
    "resolve_yesterday_ist_date",
]
