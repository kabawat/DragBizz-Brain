from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.integrations.retailer_client import RetailerResponse
from app.orchestrator.tool_selector import resolve_turn_intent
from app.schemas.tool import ToolResultStatus
from app.tools.context import ToolContext
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import (
    READ_TOOL_HANDLERS,
    list_expenses,
    list_invoices,
    list_supplier_bills,
    search_customer,
)
from app.tools.projection import project_list_supplier_bills

STORE_ID = "507f1f77bcf86cd799439011"


def _context(
    retailer: Any, question: str = "supplier bills list dikhao"
) -> ToolContext:
    return ToolContext(
        store_id=STORE_ID,
        access_token="test-token",
        retailer=retailer,
        question=question,
    )


@pytest.mark.asyncio
async def test_expense_read_passes_status_and_date_filters_to_domain_api() -> None:
    retailer = AsyncMock()
    retailer.get_expenses.return_value = RetailerResponse(
        status_code=200,
        body={"data": []},
    )

    result = await list_expenses(
        {
            "storeId": STORE_ID,
            "status": "Paid",
            "category": "rent",
            "startDate": "2026-10-01",
            "endDate": "2026-10-24",
        },
        _context(retailer, "paid rent expenses in October"),
    )

    assert result.result_status == ToolResultStatus.SUCCESS_EMPTY
    retailer.get_expenses.assert_awaited_once_with(
        access_token="test-token",
        store_id=STORE_ID,
        limit=20,
        category="rent",
        start_date="2026-10-01",
        end_date="2026-10-24",
        status="Paid",
    )


@pytest.mark.asyncio
async def test_supplier_bill_list_uses_bill_domain_and_preserves_pagination() -> None:
    retailer = AsyncMock()
    retailer.get_supplier_bills.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": [
                {
                    "_id": "bill-1",
                    "billNumber": "SB-1001",
                    "supplier": {"_id": "supplier-1", "name": "Kishan Traders"},
                    "billDate": "2026-10-10T00:00:00Z",
                    "dueDate": "2026-10-20T00:00:00Z",
                    "totalAmount": 1200,
                    "paidAmount": 200,
                    "dueAmount": 1000,
                    "paymentStatus": "PARTIAL",
                    "billStatus": "PENDING",
                    "isOverdue": True,
                    "internalStoreField": "must not leak",
                }
            ],
            "meta": {
                "pagination": {
                    "hasNextPage": True,
                    "nextCursor": "cursor-2",
                    "total": 37,
                }
            },
        },
    )

    result = await list_supplier_bills(
        {
            "storeId": STORE_ID,
            "status": "PENDING",
            "paymentStatus": "PARTIAL",
            "supplierId": "507f1f77bcf86cd799439012",
            "startDate": "2026-10-01",
            "endDate": "2026-10-31",
            "limit": 10,
        },
        _context(retailer),
    )

    assert result.success is True
    assert result.result_status == ToolResultStatus.SUCCESS_PARTIAL
    assert result.data["bills"][0]["billNumber"] == "SB-1001"
    assert result.data["bills"][0]["supplier"]["name"] == "Kishan Traders"
    assert result.data["pagination"] == {
        "hasMore": True,
        "nextCursor": "cursor-2",
        "totalCount": 37,
        "pageSize": 10,
    }
    assert "internalStoreField" not in result.data["bills"][0]
    retailer.get_supplier_bills.assert_awaited_once_with(
        access_token="test-token",
        store_id=STORE_ID,
        limit=10,
        status="PENDING",
        payment_status="PARTIAL",
        supplier_id="507f1f77bcf86cd799439012",
        start_date="2026-10-01",
        end_date="2026-10-31",
        search=None,
    )

    projected = project_list_supplier_bills(result.data)
    assert projected["bills"][0]["dueAmount"] == 1000
    assert projected["bills"][0]["supplier"]["name"] == "Kishan Traders"
    assert projected["pagination"]["hasMore"] is True


@pytest.mark.asyncio
async def test_supplier_bill_date_range_requires_both_dates() -> None:
    retailer = AsyncMock()
    result = await list_supplier_bills(
        {"storeId": STORE_ID, "startDate": "2026-10-01"},
        _context(retailer),
    )

    assert result.result_status == ToolResultStatus.INVALID_INPUT
    retailer.get_supplier_bills.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrecognized_success_payload_is_not_claimed_as_empty() -> None:
    retailer = AsyncMock()
    retailer.get_supplier_bills.return_value = RetailerResponse(
        status_code=200,
        body={"data": {"unexpected": "shape"}},
    )

    result = await list_supplier_bills({"storeId": STORE_ID}, _context(retailer))

    assert result.success is False
    assert result.result_status == ToolResultStatus.INTERNAL_ERROR
    assert result.data["code"] == "RESPONSE_SCHEMA_MISMATCH"


@pytest.mark.asyncio
async def test_bad_customer_and_invoice_shapes_are_not_reported_as_empty() -> None:
    retailer = AsyncMock()
    retailer.get_customers.return_value = RetailerResponse(
        status_code=200,
        body={"data": {"unexpected": "shape"}},
    )
    customer = await search_customer(
        {"storeId": STORE_ID, "query": "Vikas"},
        _context(retailer, "customer Vikas details"),
    )
    assert customer.success is False
    assert customer.result_status == ToolResultStatus.INTERNAL_ERROR

    retailer.list_invoices.return_value = RetailerResponse(
        status_code=200,
        body={"data": {"unexpected": "shape"}},
    )
    invoices = await list_invoices({"storeId": STORE_ID}, _context(retailer))
    assert invoices.success is False
    assert invoices.result_status == ToolResultStatus.INTERNAL_ERROR


def test_supplier_bill_tool_routes_separately_from_purchase_orders() -> None:
    definitions = {tool.name: tool for tool in READ_TOOL_DEFINITIONS}
    assert "list_supplier_bills" in definitions
    assert "list_supplier_bills" in READ_TOOL_HANDLERS
    assert definitions["list_supplier_bills"].required_permissions == (
        "bills:read",
    )

    intent = resolve_turn_intent(
        "pending supplier bills list dikhao",
        available=frozenset(definitions),
    )
    assert "list_supplier_bills" in intent.tool_names
    assert "list_purchase_orders" not in intent.tool_names
