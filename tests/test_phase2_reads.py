"""Tests for Phase 2: Dukaan ke baaki reads.

Validates tool definitions, handlers, projections, and intent routing
for stock_items, list_invoices, expenses, cashbook, suppliers,
purchase orders, bills, GST, sales orders, staff, and detailed analytics.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.integrations.retailer_client import RetailerHttpError, RetailerResponse
from app.orchestrator.tool_selector import resolve_turn_intent
from app.prompts.system.chat import build_chat_system_prompt
from app.schemas.tool import ToolResultStatus, ToolRisk
from app.tools.context import ToolContext
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import (
    READ_TOOL_HANDLERS,
    bill_summary,
    cashbook_summary,
    customer_detailed_analytics,
    expense_summary,
    gst_summary,
    invoice_detailed_analytics,
    list_expenses,
    list_invoices,
    list_purchase_orders,
    list_sales_orders,
    list_staff,
    search_supplier,
    stock_summary,
    stock_items,
    supplier_summary,
)
from app.tools.projection import (
    TOOL_PROJECTORS,
    project_bill_summary,
    project_cashbook_summary,
    project_customer_detailed_analytics,
    project_expense_summary,
    project_gst_summary,
    project_invoice_detailed_analytics,
    project_list_expenses,
    project_list_invoices,
    project_list_purchase_orders,
    project_list_sales_orders,
    project_list_staff,
    project_search_supplier,
    project_stock_summary,
    project_stock_items,
    project_supplier_summary,
)

STORE_ID = "507f1f77bcf86cd799439011"
PHASE2_TOOL_NAMES = {
    "stock_items",
    "list_invoices",
    "expense_summary",
    "list_expenses",
    "cashbook_summary",
    "search_supplier",
    "supplier_summary",
    "list_purchase_orders",
    "bill_summary",
    "gst_summary",
    "list_sales_orders",
    "list_staff",
    "customer_detailed_analytics",
    "invoice_detailed_analytics",
}


def _dummy_context(retailer: Any) -> ToolContext:
    return ToolContext(
        store_id=STORE_ID,
        access_token="test-token",
        retailer=retailer,
        question="test question",
    )


def test_phase2_tool_definitions_registered() -> None:
    defined_names = {t.name for t in READ_TOOL_DEFINITIONS}
    for name in PHASE2_TOOL_NAMES:
        assert name in defined_names
        assert name in READ_TOOL_HANDLERS
        assert name in TOOL_PROJECTORS

    for tool in READ_TOOL_DEFINITIONS:
        if tool.name in PHASE2_TOOL_NAMES:
            assert tool.risk == ToolRisk.READ
            assert tool.allows_parallel is True
            assert "storeId" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_stock_items_handler_and_projection() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_stock_items.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "items": [
                    {
                        "id": f"item-{i}",
                        "name": f"Product {i}",
                        "sku": f"SKU-{i}",
                        "quantity": 10 + i,
                        "stockStatus": "IN_STOCK",
                        "sellingPrice": 100 + i,
                        "purchasePrice": 80 + i,
                        "extraInternalField": "strip_me",
                    }
                    for i in range(50)
                ]
            }
        },
    )
    ctx = _dummy_context(mock_retailer)
    result = await stock_items({"storeId": STORE_ID}, ctx)

    assert result.success is True
    # Handler caps at 30 items
    assert result.data["count"] == 30
    assert len(result.data["items"]) == 30
    assert result.data["coverage"] == "scanned 30 items"

    projected = project_stock_items(result.data)
    assert projected["count"] == 30
    assert "extraInternalField" not in projected["items"][0]
    assert projected["items"][0]["sku"] == "SKU-0"


@pytest.mark.asyncio
async def test_list_invoices_handler_and_projection() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.list_invoices.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "invoices": [
                    {
                        "id": f"inv-{i}",
                        "invoiceNumber": f"INV-2025-{i}",
                        "customer": {
                            "id": "c1",
                            "name": "Ramesh",
                            "phone": "9876543210",
                        },
                        "invoiceDate": "2025-01-15",
                        "grandTotal": 500.0,
                        "paymentStatus": "PAID",
                        "invoiceStatus": "RELEASED",
                        "items": [{"name": "Item A"}],
                        "secretDbField": "hidden",
                    }
                    for i in range(25)
                ]
            }
        },
    )
    ctx = _dummy_context(mock_retailer)
    result = await list_invoices({"storeId": STORE_ID, "limit": 20}, ctx)

    assert result.success is True
    assert result.data["count"] == 20
    assert result.data["status"] == "RELEASED"

    projected = project_list_invoices(result.data)
    assert projected["count"] == 20
    assert "secretDbField" not in projected["invoices"][0]
    assert projected["invoices"][0]["invoiceNumber"] == "INV-2025-0"
    assert projected["invoices"][0]["customer"]["name"] == "Ramesh"
    assert projected["pagination"]["hasMore"] is True
    assert projected["pagination"]["pageSize"] == 20
    mock_retailer.list_invoices.assert_awaited_once_with(
        access_token="test-token",
        store_id=STORE_ID,
        limit=20,
        invoice_status="RELEASED",
        payment_status=None,
        customer_id=None,
        start_date=None,
        end_date=None,
        include_items=False,
        next_cursor=None,
    )


@pytest.mark.asyncio
async def test_expense_summary_and_list_expenses() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_expense_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "totals": {
                    "totalExpenses": 15,
                    "totalAmount": 12500.0,
                    "paidAmount": 10000.0,
                    "pendingAmount": 2500.0,
                    "unused": "skip",
                },
                "byCategory": [{"category": "Rent", "amount": 8000}],
            }
        },
    )
    mock_retailer.get_expenses.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "expenses": [
                    {
                        "id": "e1",
                        "expenseNumber": "EXP-01",
                        "title": "Shop Tea",
                        "category": "Food",
                        "amount": 250.0,
                        "paymentMode": "CASH",
                        "date": "2025-02-01",
                        "status": "PAID",
                    },
                    {
                        "id": "e2",
                        "title": "Shop rent",
                        "category": "Rent",
                        "amount": 20000.0,
                        "paymentMode": "CASH",
                        "date": "2025-02-01",
                        "status": "UNPAID",
                    },
                ]
            }
        },
    )
    ctx = _dummy_context(mock_retailer)
    summary_res = await expense_summary({"storeId": STORE_ID}, ctx)
    assert summary_res.success is True
    assert summary_res.data["totals"]["totalAmount"] == 12500.0

    projected_summary = project_expense_summary(summary_res.data)
    assert "unused" not in projected_summary["totals"]

    list_res = await list_expenses({"storeId": STORE_ID, "limit": 10}, ctx)
    assert list_res.success is True
    assert list_res.data["count"] == 2

    projected_list = project_list_expenses(list_res.data)
    assert projected_list["expenses"][0]["title"] == "Shop Tea"
    assert projected_list["expenses"][1]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_expense_summary_maps_core_counts_amounts_and_category_map() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_expense_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "counts": {
                    "totalExpenses": 4,
                    "paidExpenses": 1,
                    "pendingExpenses": 3,
                    "todayExpenses": 2,
                },
                "amounts": {
                    "totalAmount": 2400.0,
                    "paidAmount": 500.0,
                    "pendingAmount": 1900.0,
                    "todayAmount": 800.0,
                },
                "byCategory": {
                    "Rent": {"count": 1, "amount": 1500.0},
                    "Utilities": {"count": 3, "amount": 900.0},
                },
            }
        },
    )
    result = await expense_summary({}, _dummy_context(mock_retailer))
    projected = project_expense_summary(result.data)

    assert projected["totals"]["totalExpenses"] == 4
    assert projected["totals"]["pendingExpenses"] == 3
    assert projected["totals"]["totalAmount"] == 2400.0
    assert {row["category"]: row["amount"] for row in projected["byCategory"]} == {
        "Rent": 1500.0,
        "Utilities": 900.0,
    }


@pytest.mark.asyncio
async def test_stock_summary_preserves_cost_coverage_state() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_stock.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "totals": {"totalSkus": 3, "availableQuantity": 7, "outOfStockItems": 1},
                "valueSummary": {
                    "totalStockValue": 1050.0,
                    "averageCost": 150.0,
                    "costedQuantity": 7,
                    "unvaluedQuantity": 0,
                    "valueComplete": True,
                },
            }
        },
    )
    result = await stock_summary({}, _dummy_context(mock_retailer))
    projected = project_stock_summary(result.data)

    assert projected["totals"]["availableQuantity"] == 7
    assert projected["valueSummary"]["totalStockValue"] == 1050.0
    assert projected["valueSummary"]["valueComplete"] is True


@pytest.mark.asyncio
async def test_cashbook_summary_handler() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_cashbook_summary.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "openingBalance": 1000.0,
                "closingBalance": 3500.0,
                "totalCashIn": 4000.0,
                "totalCashOut": 1500.0,
                "netBalance": 2500.0,
                "cashSales": 3000.0,
                "dayStatus": "OPEN",
            }
        },
    )
    ctx = _dummy_context(mock_retailer)
    result = await cashbook_summary({"storeId": STORE_ID}, ctx)
    assert result.success is True
    assert result.data["openingBalance"] == 1000.0

    projected = project_cashbook_summary(result.data)
    assert projected["closingBalance"] == 3500.0
    assert projected["dayStatus"] == "OPEN"


@pytest.mark.asyncio
async def test_cashbook_summary_maps_date_range_response() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_cashbook_summary.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "from": "2026-10-20",
                "to": "2026-10-21",
                "days": [
                    {"openingBalance": 1000.0, "closingBalance": 1450.0, "totalCashIn": 700.0, "totalCashOut": 250.0, "entryCount": 3},
                    {"openingBalance": 1450.0, "closingBalance": 1800.0, "totalCashIn": 500.0, "totalCashOut": 150.0, "entryCount": 2},
                ],
                "totals": {"cashIn": 1200.0, "cashOut": 400.0, "netFlow": 800.0},
            }
        },
    )
    result = await cashbook_summary({"fromDate": "2026-10-20", "toDate": "2026-10-21"}, _dummy_context(mock_retailer))
    projected = project_cashbook_summary(result.data)

    assert projected["from"] == "2026-10-20"
    assert projected["to"] == "2026-10-21"
    assert projected["openingBalance"] == 1000.0
    assert projected["closingBalance"] == 1800.0
    assert projected["totalCashIn"] == 1200.0
    assert projected["totalCashOut"] == 400.0
    assert projected["netBalance"] == 800.0
    assert projected["dayCount"] == 2
    assert projected["entryCount"] == 5


@pytest.mark.asyncio
async def test_supplier_and_po_handlers() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_suppliers.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "suppliers": [
                    {
                        "id": "sup-1",
                        "name": "Kishan Trader",
                        "phone": "9812345678",
                        "email": "kishan@example.com",
                        "companyName": "Kishan Traders Pvt Ltd",
                        "gstNumber": "07AAAAA0000A1Z5",
                        "account": {"totalDue": 15000.0},
                    }
                ]
            }
        },
    )
    mock_retailer.get_supplier_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "counts": {
                    "totalSuppliers": 12,
                    "activeSuppliers": 10,
                    "withDues": 4,
                },
                "amounts": {
                    "totalPayable": 50000.0,
                    "totalPaid": 35000.0,
                    "totalDue": 15000.0,
                },
            }
        },
    )
    mock_retailer.get_purchase_orders.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "purchaseOrders": [
                    {
                        "id": "po-1",
                        "poNumber": "PO-2025-01",
                        "supplier": {"id": "sup-1", "name": "Kishan Trader"},
                        "poDate": "2025-01-10",
                        "status": "APPROVED",
                        "approvalStatus": "APPROVED",
                        "totalAmount": 25000.0,
                        "items": [{}, {}],
                    }
                ]
            }
        },
    )
    ctx = ToolContext(
        **{
            **_dummy_context(mock_retailer).__dict__,
            "question": "Kishan supplier phone email and due balance",
        }
    )

    s_res = await search_supplier({"storeId": STORE_ID, "query": "Kishan"}, ctx)
    assert s_res.success is True
    assert s_res.data["suppliers"][0]["totalDue"] == 15000.0

    projected_s = project_search_supplier(s_res.data)
    assert projected_s["suppliers"][0]["name"] == "Kishan Trader"

    sum_res = await supplier_summary({"storeId": STORE_ID}, ctx)
    assert sum_res.success is True
    assert sum_res.data["counts"]["totalSuppliers"] == 12

    projected_sum = project_supplier_summary(sum_res.data)
    assert projected_sum["amounts"]["totalDue"] == 15000.0

    po_res = await list_purchase_orders({"storeId": STORE_ID}, ctx)
    assert po_res.success is True
    assert po_res.data["purchaseOrders"][0]["poNumber"] == "PO-2025-01"

    projected_po = project_list_purchase_orders(po_res.data)
    assert projected_po["purchaseOrders"][0]["supplier"]["name"] == "Kishan Trader"


@pytest.mark.asyncio
async def test_bill_summary_and_gst_summary() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_bill_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "counts": {
                    "totalBills": 40,
                    "paidBills": 30,
                    "pendingBills": 10,
                    "overdueBills": 2,
                },
                "amounts": {
                    "totalPayable": 80000.0,
                    "totalPaid": 60000.0,
                    "totalDue": 20000.0,
                    "totalGst": 9600.0,
                },
            }
        },
    )
    mock_retailer.get_gst_summary.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "period": "2025-01",
                "totalTaxableAmount": 100000.0,
                "totalTax": 18000.0,
                "cgst": 9000.0,
                "sgst": 9000.0,
                "igst": 0.0,
                "invoiceCount": 45,
            }
        },
    )
    mock_retailer.get_gst_health_score.return_value = RetailerResponse(
        status_code=200,
        body={"data": {"healthScore": 95}},
    )
    ctx = _dummy_context(mock_retailer)

    bill_res = await bill_summary({"storeId": STORE_ID}, ctx)
    assert bill_res.success is True
    assert bill_res.data["counts"]["overdueBills"] == 2

    projected_bills = project_bill_summary(bill_res.data)
    assert projected_bills["amounts"]["totalDue"] == 20000.0

    gst_args = {"storeId": STORE_ID, "month": "1", "year": "2025"}
    gst_res = await gst_summary(gst_args, ctx)
    assert gst_res.success is True
    assert gst_res.data["totalTax"] == 18000.0
    assert gst_res.data["healthScore"] == 95

    projected_gst = project_gst_summary(gst_res.data)
    assert projected_gst["healthScore"] == 95
    assert projected_gst["period"] == "2025-01"


@pytest.mark.asyncio
async def test_sales_orders_and_staff_handlers() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_sales_orders.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "orders": [
                    {
                        "id": "so-1",
                        "orderNumber": "SO-001",
                        "customer": {
                            "id": "c2",
                            "name": "Amit",
                            "phone": "9811111111",
                        },
                        "orderDate": "2025-01-20",
                        "status": "CONFIRMED",
                        "paymentStatus": "PAID",
                        "totalAmount": 1200.0,
                    }
                ]
            }
        },
    )
    mock_retailer.get_staff.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "staff": [
                    {
                        "id": "st-1",
                        "name": "Vikas Sharma",
                        "phone": "9998887770",
                        "role": "BILLING_OPERATOR",
                        "status": "ACTIVE",
                    }
                ]
            }
        },
    )
    ctx = _dummy_context(mock_retailer)

    so_res = await list_sales_orders({"storeId": STORE_ID}, ctx)
    assert so_res.success is True
    assert so_res.data["salesOrders"][0]["orderNumber"] == "SO-001"

    projected_so = project_list_sales_orders(so_res.data)
    assert projected_so["salesOrders"][0]["customer"]["name"] == "Amit"

    staff_res = await list_staff({"storeId": STORE_ID}, ctx)
    assert staff_res.success is True
    assert staff_res.data["staff"][0]["name"] == "Vikas Sharma"

    projected_staff = project_list_staff(staff_res.data)
    assert projected_staff["staff"][0]["role"] == "BILLING_OPERATOR"


@pytest.mark.asyncio
async def test_detailed_analytics_handlers() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_customer_detailed_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "summary": {"totalCustomers": 150},
                "growth": {"growthRate": 12.5},
            }
        },
    )
    mock_retailer.get_invoice_detailed_analytics.return_value = RetailerResponse(
        status_code=200,
        body={"data": {"summary": {"totalRevenue": 250000.0}, "trends": {}}},
    )
    ctx = _dummy_context(mock_retailer)

    cust_det = await customer_detailed_analytics(
        {"storeId": STORE_ID, "periodDays": 30}, ctx
    )
    assert cust_det.success is True
    assert cust_det.data["growth"]["growthRate"] == 12.5

    inv_det = await invoice_detailed_analytics(
        {"storeId": STORE_ID, "periodDays": 15}, ctx
    )
    assert inv_det.success is True
    assert inv_det.data["summary"]["totalRevenue"] == 250000.0

    proj_cust = project_customer_detailed_analytics(cust_det.data)
    assert proj_cust["summary"]["totalCustomers"] == 150

    proj_inv = project_invoice_detailed_analytics(inv_det.data)
    assert proj_inv["summary"]["totalRevenue"] == 250000.0


@pytest.mark.asyncio
async def test_failure_handling_in_handlers() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.get_stock_items.side_effect = RetailerHttpError(
        status_code=500, code="RETAILER_ERROR", message="Internal DB failure"
    )
    ctx = _dummy_context(mock_retailer)
    result = await stock_items({"storeId": STORE_ID}, ctx)
    assert result.success is False
    assert result.data["code"] == "RETAILER_ERROR"
    assert result.data["message"] == (
        "Store data is temporarily unavailable; the result could not be verified."
    )


@pytest.mark.asyncio
async def test_invoice_list_marks_partial_page_without_inventing_total() -> None:
    mock_retailer = AsyncMock()
    mock_retailer.list_invoices.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "invoices": [
                    {
                        "id": f"inv-{i}",
                        "invoiceNumber": f"INV-{i}",
                        "grandTotal": 100 + i,
                    }
                    for i in range(5)
                ]
            }
        },
    )

    result = await list_invoices(
        {"storeId": STORE_ID, "limit": 2}, _dummy_context(mock_retailer)
    )

    assert result.result_status == ToolResultStatus.SUCCESS_PARTIAL
    assert result.returned_count == 2
    assert result.total_count is None
    assert result.pagination.has_more is True
    assert result.pagination.page_size == 2
    assert len(result.data["invoices"]) == 2


@pytest.mark.parametrize("limit", [1, 3, 5])
@pytest.mark.asyncio
async def test_invoice_list_returns_the_requested_page_size(limit: int) -> None:
    retailer = AsyncMock()
    retailer.list_invoices.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "invoices": [
                    {"id": f"inv-{index}", "invoiceNumber": f"INV-{index}"}
                    for index in range(limit)
                ],
                "pagination": {
                    "hasNextPage": True,
                    "nextCursor": "b" * 24,
                    "limit": limit,
                    "total": limit,
                },
            }
        },
    )

    result = await list_invoices(
        {"storeId": STORE_ID, "limit": limit}, _dummy_context(retailer)
    )

    assert result.result_status == ToolResultStatus.SUCCESS_PARTIAL
    assert result.returned_count == limit
    assert len(result.data["invoices"]) == limit
    assert result.pagination.page_size == limit
    assert result.pagination.next_cursor == "b" * 24


@pytest.mark.asyncio
async def test_invoice_list_empty_result_stays_successfully_empty() -> None:
    retailer = AsyncMock()
    retailer.list_invoices.return_value = RetailerResponse(
        status_code=200, body={"data": {"invoices": []}}
    )

    result = await list_invoices(
        {"storeId": STORE_ID}, _dummy_context(retailer)
    )

    assert result.result_status == ToolResultStatus.SUCCESS_EMPTY
    assert result.returned_count == 0
    assert result.data["invoices"] == []


@pytest.mark.asyncio
async def test_invoice_list_uses_opaque_cursor_and_preserves_all_requested_rows() -> None:
    mock_retailer = AsyncMock()
    cursor = "a" * 24
    mock_retailer.list_invoices.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "invoices": [
                    {
                        "id": f"id-{i}",
                        "invoiceNumber": f"INV-2026-VERY-LONG-{i}-\u540d\u524d-\ud83d\uded2",
                        "customer": {"id": "customer-1", "name": "\u0ba8\u0bbe\u0bae\u0bae"},
                        "invoiceDate": "2026-10-25T09:30:00+05:30",
                        "grandTotal": 123456.78,
                        "paymentStatus": "PARTIALLY_PAID",
                        "invoiceStatus": "RELEASED",
                        "items": [{"name": "hidden line detail"}],
                    }
                    for i in range(50)
                ],
                "pagination": {
                    "hasNextPage": True,
                    "nextCursor": cursor,
                    "limit": 50,
                    # Core's current `total` field is the page size, not an all-time total.
                    "total": 50,
                },
            }
        },
    )

    result = await list_invoices(
        {"storeId": STORE_ID, "limit": 50, "nextCursor": cursor},
        _dummy_context(mock_retailer),
    )
    projected = project_list_invoices(result.data)

    assert result.result_status == ToolResultStatus.SUCCESS_PARTIAL
    assert result.returned_count == 50
    assert result.total_count is None
    assert result.pagination.next_cursor == cursor
    assert len(projected["invoices"]) == 50
    assert projected["invoices"][0]["invoiceNumber"].endswith("\u540d\u524d-\ud83d\uded2")
    assert projected["invoices"][0]["customer"]["name"] == "\u0ba8\u0bbe\u0bae\u0bae"
    assert projected["invoices"][0]["totalAmount"] == 123456.78
    assert projected["invoices"][0]["itemCount"] == 1
    assert "items" not in projected["invoices"][0]
    mock_retailer.list_invoices.assert_awaited_once_with(
        access_token="test-token",
        store_id=STORE_ID,
        limit=50,
        invoice_status="RELEASED",
        payment_status=None,
        customer_id=None,
        start_date=None,
        end_date=None,
        include_items=False,
        next_cursor=cursor,
    )


@pytest.mark.asyncio
async def test_invalid_invoice_cursor_is_rejected_without_store_call() -> None:
    retailer = AsyncMock()
    result = await list_invoices(
        {"storeId": STORE_ID, "nextCursor": "not-a-cursor"},
        _dummy_context(retailer),
    )

    assert result.result_status == ToolResultStatus.INVALID_INPUT
    assert result.data["code"] == "TOOL_ARGS_INVALID"
    retailer.list_invoices.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_invoice_date_is_not_reported_as_not_found() -> None:
    mock_retailer = AsyncMock()
    result = await list_invoices(
        {"storeId": STORE_ID, "startDate": "2026-99-99"},
        _dummy_context(mock_retailer),
    )

    assert result.success is False
    assert result.result_status == ToolResultStatus.INVALID_INPUT
    assert result.data["code"] == "TOOL_ARGS_INVALID"
    mock_retailer.list_invoices.assert_not_called()


def test_intent_routing_for_phase2_queries() -> None:
    available = frozenset(t.name for t in READ_TOOL_DEFINITIONS)

    # Stock items
    intent = resolve_turn_intent("stock items dikhao", available=available)
    assert "stock_items" in intent.tool_names

    # Invoices
    intent = resolve_turn_intent("purane bill dikhao", available=available)
    assert "list_invoices" in intent.tool_names

    # Expense
    intent = resolve_turn_intent("aaj ka kharcha kitna hua", available=available)
    assert "expense_summary" in intent.tool_names
    assert "list_expenses" in intent.tool_names

    # Cashbook
    intent = resolve_turn_intent("galle ka hisaab dikhao", available=available)
    assert "cashbook_summary" in intent.tool_names

    # Finance overview must include payable and payment reads as well as cashbook.
    intent = resolve_turn_intent(
        "aaj ke cashbook ka opening, cash in, cash out, closing balance aur entry count batao",
        available=available,
        use_domain_routing=True,
    )
    assert "cashbook_summary" in intent.tool_names
    assert "bill_summary" in intent.tool_names

    # Supplier
    intent = resolve_turn_intent("suppliers list", available=available)
    assert "search_supplier" in intent.tool_names

    # Purchase Orders
    intent = resolve_turn_intent("pending purchase orders dikhao", available=available)
    assert "list_purchase_orders" in intent.tool_names

    # Bills
    intent = resolve_turn_intent("kitne bill baki hain", available=available)
    assert "bill_summary" in intent.tool_names

    # GST
    intent = resolve_turn_intent("gst report dikhao", available=available)
    assert "gst_summary" in intent.tool_names

    # Sales Orders
    intent = resolve_turn_intent("sales orders dikhao", available=available)
    assert "list_sales_orders" in intent.tool_names

    # Staff
    intent = resolve_turn_intent("kitne staff kaam karte hain", available=available)
    assert "list_staff" in intent.tool_names


def test_chat_system_prompt_includes_store_reads_rule() -> None:
    phase2_tools = [
        t for t in READ_TOOL_DEFINITIONS if t.name in {"stock_items", "expense_summary"}
    ]
    prompt = build_chat_system_prompt(
        language="hi",
        store_id=STORE_ID,
        tools=phase2_tools,
        routing="tools",
    )
    assert "Store data (invoices, stock rows, expenses" in prompt


@pytest.mark.asyncio
async def test_supplier_summary_core_shape_and_bill_enrichment() -> None:
    """Core returns totals: {totalSuppliers, activeSuppliers, inactiveSuppliers}."""
    mock_retailer = AsyncMock()
    # Live Core GET /analytics/suppliers shape
    mock_retailer.get_supplier_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "message": "Supplier analytics fetched successfully",
            "data": {
                "store": STORE_ID,
                "totals": {
                    "totalSuppliers": 10,
                    "activeSuppliers": 10,
                    "inactiveSuppliers": 0,
                },
                "metadata": {},
            },
        },
    )
    # Bill analytics for dues
    mock_retailer.get_bill_analytics.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "counts": {
                    "totalBills": 8,
                    "paidBills": 5,
                    "pendingBills": 3,
                    "overdueBills": 1,
                },
                "amounts": {
                    "totalPayable": 45000.0,
                    "totalPaid": 30000.0,
                    "totalDue": 15000.0,
                },
            }
        },
    )
    ctx = _dummy_context(mock_retailer)

    res = await supplier_summary({"storeId": STORE_ID}, ctx)
    assert res.success is True
    assert res.data["counts"]["totalSuppliers"] == 10
    assert res.data["counts"]["activeSuppliers"] == 10
    assert res.data["counts"]["inactiveSuppliers"] == 0
    assert res.data["amounts"]["totalDue"] == 15000.0
    assert res.data["bills"]["pendingBills"] == 3

    projected = project_supplier_summary(res.data)
    assert projected["counts"]["totalSuppliers"] == 10
    assert projected["counts"]["activeSuppliers"] == 10
    assert projected["amounts"]["totalDue"] == 15000.0
    assert projected["bills"]["overdueBills"] == 1


@pytest.mark.asyncio
async def test_create_expense_full_flow() -> None:
    from app.confirmations import InMemoryConfirmationStore
    from app.orchestrator.confirm_flow import handle_confirm
    from app.orchestrator.confirmation import stage_from_sensitive_calls
    from app.orchestrator.tool_selector import user_requested_sensitive_action
    from app.schemas.chat import ConfirmRequest
    from app.schemas.tool import ToolCall
    from app.sessions import InMemorySessionStore
    from app.tools.handlers.confirm_tools import create_expense
    from app.tools.projection import project_create_expense


    # 1. Selector routing & sensitive check
    q = "add karo kharcha aaj ka store ka rent diya he 20 hajar"
    available = frozenset({"create_expense", "expense_summary", "list_expenses"})
    intent = resolve_turn_intent(q, available=available)
    assert "create_expense" in intent.tool_names
    assert user_requested_sensitive_action(q, "create_expense") is True

    # 2. Tool handler execution (when confirmed)
    mock_retailer = AsyncMock()
    mock_retailer.create_expense.return_value = RetailerResponse(
        status_code=200,
        body={"data": {"_id": "exp_123", "title": "Store Rent", "amount": 20000.0}},
    )
    ctx = _dummy_context(mock_retailer)
    res = await create_expense(
        {
            "storeId": STORE_ID,
            "title": "Store Rent",
            "amount": 20000.0,
            "category": "Rent",
        },
        ctx,
    )
    assert res.success is True
    assert res.data["title"] == "Store Rent"
    assert res.data["amount"] == 20000.0

    # 3. Projection
    projected = project_create_expense(res.data)
    assert projected["title"] == "Store Rent"
    assert projected["amount"] == 20000.0
    assert projected["openPath"] == "/dashboard/expenses"

    # 4. Confirmation Staging
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="call-exp-1",
        name="create_expense",
        arguments={
            "storeId": STORE_ID,
            "title": "Store Rent",
            "amount": 20000.0,
            "category": "Rent",
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id="user_1",
        store_id=STORE_ID,
        session_id="sess_1",
        sensitive_calls=[call],
    )
    assert record is not None
    assert record.type == "create_expense"
    assert record.summary["title"] == "Store Rent"
    assert record.summary["amount"] == 20000.0
    assert record.summary["total"] == 20000.0
    assert record.summary["invoiceNumber"] == "Store Rent"
    assert "openPath" not in record.summary

    # 5. Confirm Flow Approval
    executor = AsyncMock()
    executor.execute_confirmations.return_value = [res]
    sessions = InMemorySessionStore()

    confirm_req = ConfirmRequest(
        action="approve",
        store_id=STORE_ID,
        session_id="sess_1",
        confirmation_id=record.confirmation_id,
        draft_id=record.draft_id,
    )
    chat_resp = await handle_confirm(
        confirm_req,
        user_id="user_1",
        request_id="req_1",
        store_id=STORE_ID,
        access_token="tok_1",
        confirmations=store,
        sessions=sessions,
        executor=executor,
        guard_output=lambda msg, **_: msg,
    )
    assert "Kharcha record ho gaya hai: ₹20000 (Store Rent)" in chat_resp.message
    assert "/dashboard/expenses" in chat_resp.message


def test_business_advisor_and_sales_trends_intent() -> None:
    from app.orchestrator.tool_selector import resolve_turn_intent
    from app.tools.definitions import READ_TOOL_DEFINITIONS

    available = {t.name for t in READ_TOOL_DEFINITIONS}

    q1 = (
        "yeh karo: Sales Trends: Pichle 7 ya 30 dino ki sales dekh kar "
        "samajh sakte hain ki kab demand zyada rehti hai."
    )
    intent1 = resolve_turn_intent(q1, available=available)
    assert intent1.routing in {"tools", "both"}
    assert "invoice_summary" in intent1.tool_names
    assert "stock_summary" in intent1.tool_names

    q2 = "sales dekhe and fir uska stock bhi and all check karke guide de"
    intent2 = resolve_turn_intent(q2, available=available)
    assert intent2.routing in {"tools", "both"}
    assert "invoice_summary" in intent2.tool_names
    assert "stock_summary" in intent2.tool_names


def test_budget_allow_synthesis() -> None:
    from app.limits.request_budget import BudgetExceeded, RequestBudget

    budget = RequestBudget(max_model_calls=2)
    budget.begin_model_call()
    budget.begin_model_call()
    assert budget.model_calls == 2

    # Normal model call raises BudgetExceeded
    with pytest.raises(BudgetExceeded):
        budget.begin_model_call(allow_synthesis=False)

    # Synthesis model call is permitted
    budget.begin_model_call(allow_synthesis=True)
    assert budget.model_calls == 3


@pytest.mark.asyncio
async def test_create_expense_chai_category_and_stream_summary() -> None:
    from app.confirmations import InMemoryConfirmationStore, normalize_expense_category
    from app.orchestrator.confirmation import stage_from_sensitive_calls
    from app.schemas.chat import ChatResponse, PendingConfirmation
    from app.schemas.tool import ToolCall

    # 1. Normalization tests
    cat, label = normalize_expense_category("Food & Refreshment", "Chai ka kharcha")
    assert cat == "daily-expenses"
    assert label == "Tea & Snacks (Chai)"

    cat2, label2 = normalize_expense_category("tea", "Chai nashta")
    assert cat2 == "daily-expenses"
    assert label2 == "Tea & Snacks (Chai)"

    # 2. Stage expense confirmation
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="call_exp_1",
        name="create_expense",
        arguments={
            "storeId": STORE_ID,
            "title": "Chai ka kharcha",
            "amount": 100.0,
            "category": "Food & Refreshment",
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id="user_1",
        store_id=STORE_ID,
        session_id="sess_1",
        sensitive_calls=[call],
    )
    assert record is not None
    assert record.summary["action"] == "create_expense"
    assert record.summary["prompt"] == "Record this expense"
    assert record.summary["category"] == "daily-expenses"
    assert record.summary["categoryLabel"] == "Tea & Snacks (Chai)"
    assert record.summary["amount"] == 100.0
    assert record.summary["total"] == 100.0

    # 3. Stream serialization includes summary
    pending = PendingConfirmation(
        confirmation_id=record.confirmation_id,
        type=record.type,
        draft_id=record.draft_id,
        summary=record.summary,
        expires_at="2026-10-19T06:00:00Z",
    )
    chat_resp = ChatResponse(
        message="Chai ka kharcha ₹100 add kar diya hai.",
        session_id="sess_1",
        request_id="req_1",
        user_id="user_1",
        provider="mock",
        model="mock",
        pending_confirmation=pending,
    )
    from app.orchestrator.chat_stream import stream_chat
    from app.schemas.chat import ChatRequest

    async def _mock_handle(*_, **__):
        return chat_resp

    req = ChatRequest(
        text="add chai kharcha",
        sessionId="sess_1",
        storeId=STORE_ID,
    )
    events = [
        e
        async for e in stream_chat(
            _mock_handle,
            req,
            user={"sub": "user_1"},
            request_id="req_1",
            store_id=STORE_ID,
            access_token="tok",
            metrics=None,
        )
    ]
    completed_event = [e for e in events if e[0] == "request.completed"][0]
    payload = completed_event[1]
    summary_payload = payload["pendingConfirmation"]["summary"]
    assert summary_payload["action"] == "create_expense"
    assert summary_payload["category"] == "daily-expenses"
    assert summary_payload["categoryLabel"] == "Tea & Snacks (Chai)"


def test_output_guard_allows_user_and_staged_numbers() -> None:
    from app.guards.output_guard import OutputGuard
    from app.orchestrator.chat_service import _extract_prior_numbers

    guard = OutputGuard()
    # User asked for ₹100 chai expense
    user_text = "add karo kharcha aaj ka chai ka 100 rupye"
    prior_numbers = _extract_prior_numbers([], current_user_text=user_text)
    assert "100" in prior_numbers

    # Assistant reply with ₹100 should be allowed by guard
    asst_reply = "Chai ka kharcha ₹100 add kar diya hai. Bas confirm kar dijiye."
    decision = guard.evaluate(asst_reply, tool_results=[], prior_numbers=prior_numbers)
    assert decision.allowed is True


def test_resolve_expense_date_prevents_llm_past_cutoff() -> None:
    from app.core.dates import current_ist_date_str, resolve_expense_date

    today = current_ist_date_str()

    # 1. User says "aaj ka chai ka kharcha" with hallucinated 2025-01-24
    d1 = resolve_expense_date(
        "2025-01-24", context_text="add karo kharcha aaj ka chai ka 160 rupye"
    )
    assert d1 == today

    # 2. Outdated year without context keyword should also be rejected
    d2 = resolve_expense_date("2025-01-24", context_text="chai kharcha")
    assert d2 == today

    # 3. None should default to today
    d3 = resolve_expense_date(None)
    assert d3 == today


def test_live_time_and_date_injected_in_prompt() -> None:
    from app.core.dates import current_ist_date_str, current_ist_time_str
    from app.prompts.system.chat import build_chat_system_prompt

    prompt = build_chat_system_prompt(
        language="hi-IN",
        store_id="store-1",
        tools=[],
    )
    today = current_ist_date_str()
    time_str = current_ist_time_str()

    assert today in prompt
    assert time_str in prompt
    assert "Current Date & Time Rule:" in prompt


def test_fast_conversational_turn() -> None:
    from app.orchestrator.conversational_auto import try_fast_conversational_turn

    # 1. Greetings
    res_hy = try_fast_conversational_turn("hy")
    assert res_hy is not None
    assert "DragBizz me aapka swagat hai" in res_hy.message

    res_namaste = try_fast_conversational_turn("namaste")
    assert res_namaste is not None
    assert "DragBizz" in res_namaste.message

    # 2. Time & Date
    res_time = try_fast_conversational_turn("exact time batao")
    assert res_time is not None
    assert "exact time" in res_time.message or "IST" in res_time.message

    res_date = try_fast_conversational_turn("aaj kya date he")
    assert res_date is not None
    assert "Aaj" in res_date.message

    # 3. Identity
    res_who = try_fast_conversational_turn("aap kaun ho")
    assert res_who is not None
    assert "DragAI" in res_who.message

    # 4. Closures
    res_close = try_fast_conversational_turn("theek hai")
    assert res_close is not None
    assert "dost" in res_close.message.lower()


def test_fast_conversational_bypasses_business_queries() -> None:
    from app.orchestrator.conversational_auto import try_fast_conversational_turn

    # Business terms must NEVER be intercepted by conversational fast path
    msg_expense = "add karo kharcha aaj ka chai ka 160 rupye"
    assert try_fast_conversational_turn(msg_expense) is None
    assert try_fast_conversational_turn("aaj ki sale kitni hui") is None
    assert try_fast_conversational_turn("chai ka stock kitna hai") is None
    assert try_fast_conversational_turn("500 rupaye jama karo") is None
    assert try_fast_conversational_turn("create invoice draft") is None
    assert try_fast_conversational_turn("customer ram ka ledger dikhao") is None


def test_light_bill_expense_selection() -> None:
    from app.orchestrator.tool_selector import (
        resolve_turn_intent,
        user_requested_sensitive_action,
    )
    from app.tools.definitions import (
        READ_TOOL_DEFINITIONS,
        SENSITIVE_TOOL_DEFINITIONS,
        WRITE_TOOL_DEFINITIONS,
    )
    from app.tools.registry import ToolRegistry

    reg = ToolRegistry()
    for d in (
        READ_TOOL_DEFINITIONS + WRITE_TOOL_DEFINITIONS + SENSITIVE_TOOL_DEFINITIONS
    ):
        reg.register(d, lambda: None)
    available = {d.name for d in reg.definitions()}

    q = (
        "1900 light bill bhra last month ka, isko add karo kharche me "
        "aur note bhi likhna last month sept ka"
    )
    intent = resolve_turn_intent(q, available=available)
    assert "create_expense" in intent.tool_names
    assert user_requested_sensitive_action(q, "create_expense") is True


@pytest.mark.asyncio
async def test_update_expense_flow_and_entity_resolution() -> None:
    import json
    from unittest.mock import AsyncMock

    from app.orchestrator.chat_context import _extract_recent_expense
    from app.orchestrator.tool_selector import resolve_turn_intent
    from app.sessions import SessionTurn
    from app.tools.handlers.write_tools import update_expense
    from app.tools.projection import project_update_expense

    # 1. Selector routing on update intent
    available = frozenset(
        {"update_expense", "create_expense", "list_expenses", "expense_summary"}
    )
    intent = resolve_turn_intent(
        "nahi nahi yeh update karo iska overdue he payment",
        available=available,
    )
    assert "update_expense" in intent.tool_names

    intent2 = resolve_turn_intent(
        "iska payment overdue he",
        available=available,
        prior_user_texts=["light bill 1900 bhra"],
    )
    assert "update_expense" in intent2.tool_names

    # 2. Entity extraction from prior turn tool_context
    prior_turns = [
        SessionTurn(
            user_text="rent 20000 diya",
            assistant_text="Staged expense creation",
            tool_context=json.dumps(
                [
                    {
                        "tool": "create_expense",
                        "success": True,
                        "data": {
                            "id": "exp_abc999",
                            "title": "Electricity bill",
                            "amount": 1900.0,
                            "category": "utilities",
                            "status": "PAID",
                        },
                    }
                ]
            ),
        )
    ]
    extracted = _extract_recent_expense(prior_turns)
    assert extracted is not None
    assert extracted["id"] == "exp_abc999"
    assert extracted["title"] == "Electricity bill"
    assert extracted["amount"] == 1900.0

    # 3. Tool execution
    mock_retailer = AsyncMock()
    mock_retailer.update_expense.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "_id": "exp_abc999",
                "title": "Electricity bill",
                "amount": 1900.0,
                "status": "OVERDUE",
            }
        },
    )
    ctx = _dummy_context(mock_retailer)
    res = await update_expense(
        {
            "storeId": STORE_ID,
            "expenseId": extracted["id"],
            "status": "OVERDUE",
        },
        ctx,
    )
    assert res.success is True
    assert res.data["status"] == "OVERDUE"
    assert res.data["id"] == "exp_abc999"

    # 4. Projection
    projected = project_update_expense(res.data)
    assert projected["id"] == "exp_abc999"
    assert projected["status"] == "OVERDUE"
    assert projected["openPath"] == "/dashboard/expenses"
