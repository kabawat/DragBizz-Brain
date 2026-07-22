from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.exceptions import AppError
from app.integrations.retailer_client import RetailerClient, RetailerHttpError

STORE_ID = "507f1f77bcf86cd799439011"
TOKEN = "test-access-token"


def test_get_products_forwards_store_and_bearer() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["store"] = request.url.params.get("store")
        seen["search"] = request.url.params.get("search")
        seen["limit"] = request.url.params.get("limit")
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "code": "OK",
                "data": [{"id": "p1", "name": "Atta"}],
                "pagination": {"limit": 20, "total": 1},
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            result = await retailer.get_products(
                access_token=TOKEN,
                store_id=STORE_ID,
                query="atta",
            )
        assert result.body["data"][0]["name"] == "Atta"

    asyncio.run(run())
    assert seen["path"] == "/product"
    assert seen["store"] == STORE_ID
    assert seen["search"] == "atta"
    assert seen["limit"] == "20"
    assert seen["auth"] == f"Bearer {TOKEN}"


def test_get_revenue_401_raises_tool_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            with pytest.raises(AppError) as exc_info:
                await retailer.get_revenue(
                    access_token=TOKEN, store_id=STORE_ID
                )
        assert exc_info.value.code == "TOOL_UNAUTHORIZED"

    asyncio.run(run())


def test_get_stock_403_maps_to_retailer_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            with pytest.raises(RetailerHttpError) as exc_info:
                await retailer.get_stock(
                    access_token=TOKEN, store_id=STORE_ID
                )
        assert exc_info.value.code == "TOOL_FORBIDDEN"

    asyncio.run(run())


def test_get_payments_429_maps_to_rate_limited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Too many requests"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            with pytest.raises(RetailerHttpError) as exc_info:
                await retailer.get_payments(
                    access_token=TOKEN, store_id=STORE_ID
                )
        assert exc_info.value.code == "TOOL_RATE_LIMITED"

    asyncio.run(run())
