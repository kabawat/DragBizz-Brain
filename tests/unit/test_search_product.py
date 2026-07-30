"""search_product READ tool — compact projection for LLM context."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.integrations.retailer_client import RetailerClient
from app.tools.context import ToolContext
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS, search_product

STORE_ID = "507f1f77bcf86cd799439011"
PRODUCT_ID = "707f1f77bcf86cd799439011"


def test_search_product_registered() -> None:
    names = {definition.name for definition in READ_TOOL_DEFINITIONS}
    assert "search_product" in names
    assert "search_product" in READ_TOOL_HANDLERS


def test_search_product_returns_compact_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": PRODUCT_ID,
                        "name": "Atta 10kg",
                        "sku": "ATTA-10",
                        "brand": "Aashirvaad",
                        "category": "Grocery",
                        "barcode": "890123",
                        "pricing": {
                            "basePrice": 400,
                            "mrp": 450,
                            "sellingPrice": 420,
                            "discount": 0,
                            "currency": "INR",
                            "uom": "BAG",
                        },
                        "gstInfo": {"gstRate": 5, "hsn": "1101"},
                        "status": "ACTIVE",
                        "stock": 12,
                        "images": ["https://cdn.example/atta.jpg"],
                        "timestamps": {
                            "createdAt": "2026-01-01T00:00:00Z",
                            "updatedAt": "2026-01-02T00:00:00Z",
                        },
                    }
                ],
                "pagination": {"limit": 20, "total": 1},
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
            return await search_product(
                {"storeId": STORE_ID, "query": "atta"}, context
            )

    result = asyncio.run(run())
    assert result.success is True
    assert "pagination" not in result.data
    assert result.data["items"] == [
        {
            "id": PRODUCT_ID,
            "name": "Atta 10kg",
            "sku": "ATTA-10",
            "sellingPrice": 420,
            "stock": 12,
            "taxRate": 5,
            "unit": "BAG",
            "status": "ACTIVE",
        }
    ]


def test_search_product_maps_retailer_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "No permission"})

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
            return await search_product(
                {"storeId": STORE_ID, "query": "atta"}, context
            )

    result = asyncio.run(run())
    assert result.success is False
    assert result.data["code"] == "TOOL_FORBIDDEN"
