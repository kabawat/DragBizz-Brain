from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.confirmations import (
    CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER,
    InMemoryConfirmationStore,
)
from app.core.exceptions import AppError
from app.integrations.retailer_client import (
    RetailerClient,
    RetailerHttpError,
    RetailerResponse,
)
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import stage_from_sensitive_calls
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_selector import (
    resolve_turn_intent,
    user_requested_sensitive_action,
)
from app.schemas.chat import ConfirmRequest
from app.schemas.tool import ToolCall
from app.sessions import InMemorySessionStore
from app.tools.context import ToolContext
from app.tools.definitions import SENSITIVE_TOOL_DEFINITIONS
from app.tools.handlers.confirm_tools import create_purchase_order as po_handler
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"
OTHER_STORE_ID = "507f1f77bcf86cd799439022"
SUPPLIER_ID = "507f1f77bcf86cd799439033"
PRODUCT_1 = "507f1f77bcf86cd799439044"
PRODUCT_2 = "507f1f77bcf86cd799439055"
USER_ID = "user_test_1"
SESSION_ID = "sess_test_1"


def _mock_guard(text: str, **kwargs: Any) -> str:
    return text


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    for defn in SENSITIVE_TOOL_DEFINITIONS:
        reg.register_definition(defn)
    return reg


@pytest.fixture
def validator(registry: ToolRegistry) -> ToolCallValidator:
    return ToolCallValidator(registry)


@pytest.fixture
def mock_retailer() -> AsyncMock:
    client = AsyncMock(spec=RetailerClient)
    client.create_purchase_order = AsyncMock()
    return client


def test_validator_valid_args(validator: ToolCallValidator) -> None:
    call = ToolCall(
        id="call_po_1",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "supplierName": "Metro Wholesale",
            "items": [
                {
                    "productId": PRODUCT_1,
                    "quantity": 10,
                    "productName": "Basmati Rice",
                },
                {
                    "productId": PRODUCT_2,
                    "quantity": 5,
                    "productName": "Cooking Oil",
                },
            ],
            "paymentTerms": "30_DAYS",
            "notes": "Urgent delivery please",
        },
    )
    validated = validator.validate([call], store_id=STORE_ID)
    assert len(validated) == 1
    assert validated[0].name == "create_purchase_order"
    assert validated[0].arguments["supplierId"] == SUPPLIER_ID
    assert len(validated[0].arguments["items"]) == 2


def test_validator_store_mismatch_rejected(validator: ToolCallValidator) -> None:
    call = ToolCall(
        id="call_po_bad_store",
        name="create_purchase_order",
        arguments={
            "storeId": OTHER_STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_1, "quantity": 10}],
        },
    )
    with pytest.raises(AppError) as exc_info:
        validator.validate([call], store_id=STORE_ID)
    assert exc_info.value.code == "TOOL_ARGS_INVALID"
    assert "must match the chat request storeId" in exc_info.value.message


def test_validator_missing_items_rejected(validator: ToolCallValidator) -> None:
    call = ToolCall(
        id="call_po_no_items",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [],
        },
    )
    with pytest.raises(AppError) as exc_info:
        validator.validate([call], store_id=STORE_ID)
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


def test_validator_zero_or_negative_quantity_rejected(
    validator: ToolCallValidator,
) -> None:
    call = ToolCall(
        id="call_po_bad_qty",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_1, "quantity": 0}],
        },
    )
    with pytest.raises(AppError) as exc_info:
        validator.validate([call], store_id=STORE_ID)
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


def test_validator_invalid_supplier_object_id(
    validator: ToolCallValidator,
) -> None:
    call = ToolCall(
        id="call_po_bad_supplier",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": "not-a-valid-objectid",
            "items": [{"productId": PRODUCT_1, "quantity": 5}],
        },
    )
    with pytest.raises(AppError) as exc_info:
        validator.validate([call], store_id=STORE_ID)
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


@pytest.mark.asyncio
async def test_staging_creates_structured_pending_record() -> None:
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="call_stage_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "supplierName": "Metro Wholesale",
            "items": [
                {
                    "productId": PRODUCT_1,
                    "quantity": 10,
                    "productName": "Basmati Rice",
                },
                {
                    "productId": PRODUCT_2,
                    "quantity": 20,
                    "productName": "Cooking Oil",
                },
            ],
            "paymentTerms": "30_DAYS",
            "reference": "REF-9988",
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )
    assert record is not None
    assert record.type == CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER
    assert record.status == "PENDING"
    assert record.store_id == STORE_ID
    assert record.user_id == USER_ID
    assert record.summary["action"] == "create_purchase_order"
    assert record.summary["supplierName"] == "Metro Wholesale"
    assert record.summary["itemCount"] == 2
    assert record.summary["totalQuantity"] == 30
    assert record.summary["reference"] == "REF-9988"

    public = record.to_public()
    assert public["confirmationId"] == record.confirmation_id
    assert public["type"] == CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER
    assert public["summary"]["totalQuantity"] == 30


@pytest.mark.asyncio
async def test_handler_success(mock_retailer: AsyncMock) -> None:
    mock_retailer.create_purchase_order.return_value = RetailerResponse(
        status_code=201,
        body={
            "status": True,
            "message": "Purchase Order created successfully",
            "data": {
                "id": "po_real_123",
                "poNumber": "PO-2026-0042",
                "status": "DRAFT",
            },
        },
    )
    context = ToolContext(
        retailer=mock_retailer,
        access_token="tok_123",
        store_id=STORE_ID,
        question="po banao",
    )
    args = {
        "storeId": STORE_ID,
        "supplierId": SUPPLIER_ID,
        "supplierName": "Metro Wholesale",
        "items": [{"productId": PRODUCT_1, "quantity": 10}],
        "idempotencyKey": "stable_idem_key_1",
    }
    result = await po_handler(args, context)
    assert result.success is True
    assert result.tool == "create_purchase_order"
    assert result.data["id"] == "po_real_123"
    assert result.data["poNumber"] == "PO-2026-0042"
    assert result.data["totalQuantity"] == 10
    assert result.data["status"] == "DRAFT"
    assert result.data["openPath"] == "/dashboard/purchase-orders/po_real_123"

    mock_retailer.create_purchase_order.assert_awaited_once_with(
        access_token="tok_123",
        store_id=STORE_ID,
        supplier_id=SUPPLIER_ID,
        items=[{"productId": PRODUCT_1, "quantity": 10}],
        payment_terms=None,
        reference=None,
        notes=None,
        expected_delivery_date=None,
        idempotency_key="stable_idem_key_1",
    )


@pytest.mark.asyncio
async def test_handler_error_propagation(mock_retailer: AsyncMock) -> None:
    mock_retailer.create_purchase_order.side_effect = RetailerHttpError(
        status_code=400,
        code="TOOL_ARGS_INVALID",
        message="Supplier does not exist in this store",
    )
    context = ToolContext(
        retailer=mock_retailer,
        access_token="tok_123",
        store_id=STORE_ID,
    )
    args = {
        "storeId": STORE_ID,
        "supplierId": SUPPLIER_ID,
        "items": [{"productId": PRODUCT_1, "quantity": 10}],
    }
    result = await po_handler(args, context)
    assert result.success is False
    assert result.data["code"] == "TOOL_ARGS_INVALID"
    assert "Supplier does not exist" in result.data["message"]


@pytest.mark.asyncio
async def test_end_to_end_confirmation_flow(mock_retailer: AsyncMock) -> None:
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="call_stage_po_flow",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "supplierName": "Metro Wholesale",
            "items": [{"productId": PRODUCT_1, "quantity": 15}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )
    assert record is not None

    mock_retailer.create_purchase_order.return_value = RetailerResponse(
        status_code=201,
        body={
            "status": True,
            "message": "Purchase Order created successfully",
            "data": {
                "id": "po_flow_777",
                "poNumber": "PO-2026-0099",
                "status": "DRAFT",
            },
        },
    )

    class MockExecutor:
        async def execute_confirmations(
            self, tool_calls: list[ToolCall], **kwargs: Any
        ) -> list[Any]:
            idem_key = kwargs.get("business_idempotency_key")
            res = await po_handler(
                {**tool_calls[0].arguments, "idempotencyKey": idem_key},
                ToolContext(
                    retailer=mock_retailer,
                    access_token=kwargs.get("access_token", ""),
                    store_id=kwargs.get("store_id", ""),
                ),
            )
            return [res]

    body = ConfirmRequest(
        action="approve",
        confirmation_id=record.confirmation_id,
        session_id=SESSION_ID,
        store_id=STORE_ID,
        draft_id=record.draft_id,
    )

    resp = await handle_confirm(
        body=body,
        user_id=USER_ID,
        request_id="req_po_1",
        store_id=STORE_ID,
        access_token="tok_flow",
        confirmations=store,
        sessions=InMemorySessionStore(),
        executor=MockExecutor(),
        guard_output=_mock_guard,
    )
    assert "PO-2026-0099" in resp.message
    assert "created successfully" in resp.message

    raw_stored = store._entries[record.confirmation_id]
    assert raw_stored.status == "SUCCEEDED"
    assert raw_stored.business_idempotency_key is not None

    with pytest.raises(AppError) as exc_info:
        await handle_confirm(
            body=body,
            user_id=USER_ID,
            request_id="req_po_2",
            store_id=STORE_ID,
            access_token="tok_flow",
            confirmations=store,
            sessions=InMemorySessionStore(),
            executor=MockExecutor(),
            guard_output=_mock_guard,
        )
    assert exc_info.value.code == "CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_rejection_flow() -> None:
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="call_stage_reject",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_1, "quantity": 5}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )
    assert record is not None
    body = ConfirmRequest(
        action="reject",
        confirmation_id=record.confirmation_id,
        session_id=SESSION_ID,
        store_id=STORE_ID,
        draft_id=record.draft_id,
    )
    resp = await handle_confirm(
        body=body,
        user_id=USER_ID,
        request_id="req_po_rej",
        store_id=STORE_ID,
        access_token="tok_rej",
        confirmations=store,
        sessions=InMemorySessionStore(),
        executor=AsyncMock(),
        guard_output=_mock_guard,
    )
    assert "cancelled" in resp.message.lower()
    raw_stored = store._entries[record.confirmation_id]
    assert raw_stored.status == "REJECTED"


def test_tool_selector_exposure() -> None:
    available = frozenset(
        {
            "create_purchase_order",
            "search_supplier",
            "search_product",
            "list_purchase_orders",
            "today_sale",
        }
    )
    intent = resolve_turn_intent(
        "supplier ko 20 carton maal order karo po banao", available=available
    )
    assert "create_purchase_order" in intent.tool_names
    assert "search_supplier" in intent.tool_names
    assert "search_product" in intent.tool_names
    assert (
        user_requested_sensitive_action(
            "supplier ko po banao", "create_purchase_order"
        )
        is True
    )
    assert (
        user_requested_sensitive_action(
            "aaj ki sale kitni hui", "create_purchase_order"
        )
        is False
    )


def test_tool_selector_po_create_krna_exposes_companion_tools() -> None:
    available = frozenset(
        {
            "create_purchase_order",
            "search_supplier",
            "search_product",
            "list_purchase_orders",
        }
    )
    query = "Amul Cheese Slices ka PO create krna 10 qty amul supplier se"
    intent = resolve_turn_intent(query, available=available)
    assert intent.routing == "tools"
    assert "create_purchase_order" in intent.tool_names
    assert "search_supplier" in intent.tool_names
    assert "search_product" in intent.tool_names


@pytest.mark.asyncio
async def test_po_handler_rejects_supplier_id_as_product_id(
    mock_retailer: AsyncMock,
) -> None:
    context = ToolContext(
        store_id=STORE_ID,
        access_token="tok_123",
        retailer=mock_retailer,
    )
    args = {
        "storeId": STORE_ID,
        "supplierId": SUPPLIER_ID,
        "items": [
            {
                "productId": SUPPLIER_ID,  # Duplicate of supplier ID
                "quantity": 10,
                "productName": "Amul Cheese Slices",
            }
        ],
    }
    result = await po_handler(args, context)
    assert result.success is False
    assert result.data["code"] == "TOOL_ARGS_INVALID"
    assert "productId equal to supplierId" in result.data["message"]

