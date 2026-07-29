"""update_invoice_draft — link customer to an existing DRAFT invoice."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.confirmations import InMemoryConfirmationStore
from app.integrations.retailer_client import RetailerClient
from app.orchestrator.confirmation import stage_from_draft_result
from app.schemas.tool import ToolResult
from app.tools.context import ToolContext
from app.tools.definitions import WRITE_TOOL_DEFINITIONS
from app.tools.handlers.write_tools import (
    WRITE_TOOL_HANDLERS,
    update_invoice_draft,
)

STORE_ID = "507f1f77bcf86cd799439011"
CUSTOMER_ID = "607f1f77bcf86cd799439011"
INVOICE_ID = "807f1f77bcf86cd799439011"


def test_update_invoice_draft_registered() -> None:
    names = {definition.name for definition in WRITE_TOOL_DEFINITIONS}
    assert "update_invoice_draft" in names
    assert "update_invoice_draft" in WRITE_TOOL_HANDLERS


def test_update_invoice_draft_puts_customer() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["store"] = request.url.params.get("store")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "data": {
                    "_id": INVOICE_ID,
                    "customer": CUSTOMER_ID,
                    "totalAmount": 118,
                    "invoiceStatus": "DRAFT",
                }
            },
        )

    async def run() -> Any:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            context = ToolContext(
                access_token="token",
                store_id=STORE_ID,
                retailer=retailer,
            )
            return await update_invoice_draft(
                {
                    "storeId": STORE_ID,
                    "invoiceId": INVOICE_ID,
                    "customerId": CUSTOMER_ID,
                },
                context,
            )

    result = asyncio.run(run())
    assert seen["method"] == "PUT"
    assert seen["path"] == f"/invoices/{INVOICE_ID}"
    assert seen["store"] == STORE_ID
    assert seen["body"] == {"customer": CUSTOMER_ID}
    assert result.success is True
    assert result.data["openPath"] == f"/dashboard/invoices/{INVOICE_ID}"


def test_update_invoice_draft_requires_customer_or_items() -> None:
    async def run() -> Any:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, json={"message": "no call"})
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            context = ToolContext(
                access_token="token",
                store_id=STORE_ID,
                retailer=retailer,
            )
            return await update_invoice_draft(
                {"storeId": STORE_ID, "invoiceId": INVOICE_ID}, context
            )

    result = asyncio.run(run())
    assert result.success is False
    assert result.data["code"] == "TOOL_ARGS_INVALID"


def test_update_result_restages_pending_confirmation() -> None:
    store = InMemoryConfirmationStore(ttl_seconds=300)
    result = ToolResult(
        tool="update_invoice_draft",
        success=True,
        data={
            "_id": INVOICE_ID,
            "totalAmount": 118,
            "openPath": f"/dashboard/invoices/{INVOICE_ID}",
        },
    )
    record = stage_from_draft_result(
        store,
        user_id="user-1",
        store_id=STORE_ID,
        session_id="s1",
        result=result,
    )
    assert record is not None
    assert record.draft_id == INVOICE_ID
    assert record.summary["total"] == 118
    assert record.tool_name == "release_invoice"
