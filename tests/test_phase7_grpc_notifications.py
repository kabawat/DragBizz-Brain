"""Tests for gRPC Core integration and Notification REST API in Phase 7."""

from __future__ import annotations

from unittest.mock import MagicMock

import grpc
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.notifications import router as notifications_router
from app.config.services import ServiceSettings
from app.core.exceptions import register_exception_handlers
from app.integrations.core_grpc_client import (
    CoreGrpcCallError,
    CoreGrpcClient,
    GetActiveStoresResponse,
    GetStoreDailySummaryResponse,
    GetStoreStockSummaryResponse,
)
from app.proactive.briefing import CoreStoreProvider
from app.proactive.models import AlertSeverity, AlertType, NotificationRecord
from app.proactive.notification_store import InMemoryNotificationStore

STORE_A = "6ad49964d5cb7a1b29d4bb7a"
STORE_B = "6ad49964d5cb7a1b29d4bb7b"


def test_intelligence_grpc_defaults_to_core_container_listener_port():
    assert ServiceSettings(_env_file=None).retailer_intelligence_grpc_port == 50054
    assert CoreGrpcClient().target_address == "localhost:50054"


def test_grpc_client_fails_closed_without_tls_credentials(monkeypatch):
    client = CoreGrpcClient(target_address="localhost:5004")
    monkeypatch.setattr(
        "app.integrations.core_grpc_client.grpc.insecure_channel",
        lambda *args, **kwargs: pytest.fail("insecure gRPC fallback was attempted"),
    )
    with pytest.raises(RuntimeError, match="credentials are not configured"):
        client._get_channel()


def test_grpc_client_builds_mutual_tls_channel_from_configured_files(
    tmp_path, monkeypatch
):
    ca_path = tmp_path / "ca.crt"
    cert_path = tmp_path / "brain.crt"
    key_path = tmp_path / "brain.key"
    ca_path.write_bytes(b"test-ca")
    cert_path.write_bytes(b"test-client-cert")
    key_path.write_bytes(b"test-client-key")
    expected_channel = object()
    credentials = object()
    tls_factory = MagicMock(return_value=credentials)
    secure_factory = MagicMock(return_value=expected_channel)
    insecure_factory = MagicMock(side_effect=AssertionError("insecure fallback"))
    monkeypatch.setattr(
        "app.integrations.core_grpc_client.grpc.ssl_channel_credentials", tls_factory
    )
    monkeypatch.setattr(
        "app.integrations.core_grpc_client.grpc.secure_channel", secure_factory
    )
    monkeypatch.setattr(
        "app.integrations.core_grpc_client.grpc.insecure_channel", insecure_factory
    )

    client = CoreGrpcClient(
        target_address="localhost:5004",
        root_ca_path=str(ca_path),
        client_cert_path=str(cert_path),
        client_key_path=str(key_path),
    )
    assert client._get_channel() is expected_channel
    tls_factory.assert_called_once_with(
        root_certificates=b"test-ca",
        private_key=b"test-client-key",
        certificate_chain=b"test-client-cert",
    )
    secure_factory.assert_called_once_with(
        "localhost:5004",
        credentials,
        options=[
            ("grpc.keepalive_time_ms", 30000),
            ("grpc.keepalive_timeout_ms", 5000),
        ],
    )
    insecure_factory.assert_not_called()


@pytest.mark.parametrize(
    ("status_code", "category", "attempts"),
    [
        (grpc.StatusCode.DEADLINE_EXCEEDED, "TIMEOUT", 2),
        (grpc.StatusCode.UNAVAILABLE, "CORE_UNAVAILABLE", 2),
        (grpc.StatusCode.UNAUTHENTICATED, "AUTHENTICATION_FAILED", 1),
        (grpc.StatusCode.PERMISSION_DENIED, "AUTHORIZATION_FAILED", 1),
    ],
)
def test_grpc_client_retries_only_transient_reads_and_returns_safe_error(
    monkeypatch, status_code, category, attempts
):
    class FakeRpcError(grpc.RpcError):
        def code(self):
            return status_code

    invoker = MagicMock(side_effect=FakeRpcError())
    channel = MagicMock()
    channel.unary_unary.return_value = invoker
    client = CoreGrpcClient(timeout=0.25, max_retries=1)
    client._channel = channel
    monkeypatch.setattr("app.integrations.core_grpc_client.time.sleep", lambda _: None)

    with pytest.raises(CoreGrpcCallError) as error:
        client._invoke_with_retry(
            "/Intelligence/GetStoreDailySummary",
            lambda _: b"",
            lambda _: None,
            b"",
        )

    assert error.value.category == category
    assert error.value.status_code is status_code
    assert invoker.call_count == attempts
    assert all(call.kwargs["timeout"] == 0.25 for call in invoker.call_args_list)


# ---------------------------------------------------------------------------
# 1. CoreGrpcClient mock contract tests
# ---------------------------------------------------------------------------

def test_grpc_client_get_active_stores_parsing():
    """Verify CoreGrpcClient parses GetActiveStoresResponse accurately."""
    client = CoreGrpcClient(target_address="localhost:5004")
    
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
    client = CoreGrpcClient(target_address="localhost:5004")

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
    client = CoreGrpcClient(target_address="localhost:5004")

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


@pytest.mark.asyncio
async def test_core_store_provider_reads_bounded_pages_and_deduplicates():
    mock_grpc = MagicMock()
    first = [{"store_id": f"{i:024x}"} for i in range(50)]
    second = [{"store_id": first[-1]["store_id"]}, {"store_id": STORE_A}]
    mock_grpc.get_active_stores.side_effect = [first, second]
    provider = CoreStoreProvider(grpc_client=mock_grpc)
    stores = await provider()
    assert len(stores) == 51
    assert stores[-1] == STORE_A
    assert mock_grpc.get_active_stores.call_count == 2


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


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [
    {"sub": "usr_001"},
    {"sub": "usr_001", "stores": []},
    {"sub": "usr_001", "stores": ["malformed"]},
])
async def test_notifications_fail_closed_without_valid_store_claim(
    notification_test_app, claims
):
    from app.core.security import get_current_user

    async def mock_user():
        return claims

    notification_test_app.dependency_overrides[get_current_user] = mock_user
    transport = ASGITransport(app=notification_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/notifications", params={"storeId": STORE_A})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_notification_mark_all_read_is_store_scoped(notification_test_app):
    store: InMemoryNotificationStore = notification_test_app.state.notification_store
    for store_id, notification_id in ((STORE_A, "a"), (STORE_B, "b")):
        await store.save_notification(
            NotificationRecord(
                id=notification_id,
                storeId=store_id,
                notificationType=AlertType.DAILY_BRIEF,
                title="Brief",
                message="Summary",
                severity=AlertSeverity.INFO,
            )
        )
    from app.core.security import get_current_user

    async def mock_user():
        return {"sub": "usr_001", "stores": [STORE_A]}

    notification_test_app.dependency_overrides[get_current_user] = mock_user
    transport = ASGITransport(app=notification_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.patch("/notifications/read-all", params={"storeId": STORE_A})
        forbidden = await client.patch(
            "/notifications/read-all", params={"storeId": STORE_B}
        )
    assert res.status_code == 200
    assert res.json()["updated"] == 1
    assert forbidden.status_code == 403
    assert await store.count_unread(STORE_A) == 0
    assert await store.count_unread(STORE_B) == 1
