"""Tests for gRPC Core integration and Notification REST API in Phase 7."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.notifications import router as notifications_router
from app.core.exceptions import register_exception_handlers
from app.integrations.core_grpc_client import (
    ActiveStoreInfo,
    CoreGrpcClient,
    GetActiveStoresResponse,
    GetStoreDailySummaryResponse,
    GetStoreStockSummaryResponse,
    LowStockItem,
)
from app.proactive.briefing import CoreStoreProvider, resolve_yesterday_ist_date
from app.proactive.models import AlertSeverity, AlertType, NotificationRecord
from app.proactive.notification_store import InMemoryNotificationStore
from fastapi import FastAPI


STORE_A = "6ad49964d5cb7a1b29d4bb7a"
STORE_B = "6ad49964d5cb7a1b29d4bb7b"


# ---------------------------------------------------------------------------
# 1. CoreGrpcClient mock contract tests
# ---------------------------------------------------------------------------

def test_grpc_client_get_active_stores_parsing():
    """Verify CoreGrpcClient parses GetActiveStoresResponse accurately."""
    client = CoreGrpcClient(target_address="localhost:5001")
    
    mock_resp = GetActiveStoresResponse(
        success=True,
        message="OK",
        total=2,
    )
    s1 = mock_resp.stores.add()
    s1.storeId = STORE_A
    s1.name = "Store Alpha"
    s1.timezone = "Asia/Kolkata"

    s2 = mock_resp.stores.add()
    s2.storeId = STORE_B
    s2.name = "Store Beta"
    s2.timezone = "Asia/Kolkata"

    client._invoke_with_retry = MagicMock(return_value=mock_resp)

    stores = client.get_active_stores(limit=10, page=1)
    assert len(stores) == 2
    assert stores[0]["store_id"] == STORE_A
    assert stores[0]["name"] == "Store Alpha"
    assert stores[1]["store_id"] == STORE_B


def test_grpc_client_get_store_stock_summary_parsing():
    """Verify CoreGrpcClient parses low-stock inventory accurately."""
    client = CoreGrpcClient(target_address="localhost:5001")

    mock_resp = GetStoreStockSummaryResponse(
        success=True,
        message="OK",
        storeId=STORE_A,
    )
    i1 = mock_resp.lowStockItems.add()
    i1.productId = "prod_001"
    i1.productName = "Basmati Rice 5kg"
    i1.sku = "RICE-5KG"
    i1.availableQuantity = 3.0
    i1.lowStockThreshold = 10.0

    client._invoke_with_retry = MagicMock(return_value=mock_resp)

    items = client.get_store_stock_summary(STORE_A)
    assert len(items) == 1
    assert items[0]["product_id"] == "prod_001"
    assert items[0]["available_quantity"] == 3.0
    assert items[0]["low_stock_threshold"] == 10.0


def test_grpc_client_get_store_daily_summary_parsing():
    """Verify CoreGrpcClient parses completed-day sales summary."""
    client = CoreGrpcClient(target_address="localhost:5001")

    mock_resp = GetStoreDailySummaryResponse(
        success=True,
        message="Calculated",
        storeId=STORE_A,
        period="COMPLETED_DAY",
        periodStartUtc="2026-10-19T18:30:00.000Z",
        periodEndUtc="2026-10-20T18:30:00.000Z",
        revenue=15420.50,
        profit=3210.00,
        salesCount=42,
    )
    client._invoke_with_retry = MagicMock(return_value=mock_resp)

    summary = client.get_store_daily_summary(STORE_A)
    assert summary["success"] is True
    assert summary["revenue"] == 15420.50
    assert summary["profit"] == 3210.00
    assert summary["sales_count"] == 42
    assert summary["period"] == "COMPLETED_DAY"


@pytest.mark.asyncio
async def test_core_store_provider_uses_grpc():
    """Verify CoreStoreProvider delegates to CoreGrpcClient."""
    mock_grpc = MagicMock()
    mock_grpc.get_active_stores.return_value = [
        {"store_id": STORE_A, "name": "Store Alpha"},
        {"store_id": STORE_B, "name": "Store Beta"},
    ]

    provider = CoreStoreProvider(grpc_client=mock_grpc)
    stores = await provider()
    assert stores == [STORE_A, STORE_B]
    mock_grpc.get_active_stores.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Notification REST API tests
# ---------------------------------------------------------------------------

@pytest.fixture
def notification_test_app():
    app = FastAPI()
    app.include_router(notifications_router)
    register_exception_handlers(app)
    app.state.notification_store = InMemoryNotificationStore()
    return app


@pytest.mark.asyncio
async def test_notifications_list_unauthorized_missing_token(notification_test_app):
    """Anonymous requests must be rejected with 401."""
    transport = ASGITransport(app=notification_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/notifications", params={"storeId": STORE_A})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_notifications_list_and_pagination(notification_test_app):
    """Authenticated requests retrieve store notifications with pagination."""
    store: InMemoryNotificationStore = notification_test_app.state.notification_store
    
    # Populate test notifications
    for i in range(5):
        await store.save_notification(
            NotificationRecord(
                id=f"notif_{i}",
                storeId=STORE_A,
                notificationType=AlertType.LOW_STOCK,
                title=f"Alert {i}",
                message=f"Stock low {i}",
                severity=AlertSeverity.WARNING,
            )
        )

    # Mock user dependency
    from app.core.security import get_current_user

    async def mock_user():
        return {"sub": "usr_001", "role": "OWNER", "stores": [STORE_A]}

    notification_test_app.dependency_overrides[get_current_user] = mock_user

    transport = ASGITransport(app=notification_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch first page (limit=2)
        res = await client.get(
            "/notifications",
            params={"storeId": STORE_A, "limit": 2, "skip": 0},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["storeId"] == STORE_A
        assert len(body["items"]) == 2
        assert body["totalUnread"] == 5

        # 2. Cross-store access rejected with 403
        cross_res = await client.get(
            "/notifications",
            params={"storeId": STORE_B},
        )
        assert cross_res.status_code == 403


@pytest.mark.asyncio
async def test_notifications_mark_read(notification_test_app):
    """Mark as read updates record and rejects non-existent or cross-store."""
    store: InMemoryNotificationStore = notification_test_app.state.notification_store
    await store.save_notification(
        NotificationRecord(
            id="notif_target",
            storeId=STORE_A,
            notificationType=AlertType.DAILY_BRIEF,
            title="Daily Brief",
            message="Your daily summary",
            severity=AlertSeverity.INFO,
        )
    )

    from app.core.security import get_current_user

    async def mock_user():
        return {"sub": "usr_001", "role": "OWNER", "stores": [STORE_A]}

    notification_test_app.dependency_overrides[get_current_user] = mock_user

    transport = ASGITransport(app=notification_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Mark existing read
        patch_res = await client.patch(
            "/notifications/notif_target/read",
            params={"storeId": STORE_A},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["read"] is True

        # Verify unread count became 0
        unread = await store.count_unread(STORE_A)
        assert unread == 0

        # 2. Mark non-existent notification returns 404
        not_found_res = await client.patch(
            "/notifications/non_existent/read",
            params={"storeId": STORE_A},
        )
        assert not_found_res.status_code == 404
