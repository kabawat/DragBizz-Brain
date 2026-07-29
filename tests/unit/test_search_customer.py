"""search_customer READ tool — existing-customer lookup for bills/khata."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.integrations.retailer_client import RetailerClient
from app.tools.context import ToolContext
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS, search_customer

STORE_ID = "507f1f77bcf86cd799439011"
CUSTOMER_ID = "607f1f77bcf86cd799439011"


def test_search_customer_registered() -> None:
    names = {definition.name for definition in READ_TOOL_DEFINITIONS}
    assert "search_customer" in names
    assert "search_customer" in READ_TOOL_HANDLERS


def test_get_customers_sends_search_and_store() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["store"] = request.url.params.get("store")
        seen["search"] = request.url.params.get("search")
        return httpx.Response(200, json={"data": []})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            await retailer.get_customers(
                access_token="token",
                store_id=STORE_ID,
                query="Rajesh",
            )

    asyncio.run(run())
    assert seen["method"] == "GET"
    assert seen["path"] == "/customer"
    assert seen["store"] == STORE_ID
    assert seen["search"] == "Rajesh"


def test_search_customer_returns_compact_items_with_real_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": CUSTOMER_ID,
                        "name": "Rajesh Kumar",
                        "phone": "9876543210",
                        "email": None,
                        "companyDetails": {"gstDetail": "27ABCDE1234F1Z5"},
                        "source": "MANUAL",
                    }
                ]
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
            return await search_customer(
                {"storeId": STORE_ID, "query": "Rajesh"}, context
            )

    result = asyncio.run(run())
    assert result.success is True
    items = result.data["items"]
    assert items == [
        {
            "id": CUSTOMER_ID,
            "name": "Rajesh Kumar",
            "phone": "9876543210",
            "email": None,
        }
    ]


def test_search_customer_maps_retailer_error() -> None:
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
            return await search_customer(
                {"storeId": STORE_ID, "query": "Rajesh"}, context
            )

    result = asyncio.run(run())
    assert result.success is False
    assert result.data["code"] == "TOOL_FORBIDDEN"
