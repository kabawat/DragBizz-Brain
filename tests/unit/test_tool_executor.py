from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerClient
from app.schemas.tool import ToolCall
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register(definition, READ_TOOL_HANDLERS[definition.name])
    return registry


def test_executor_runs_today_sale() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/analytics/revenue"
        assert request.url.params.get("store") == STORE_ID
        return httpx.Response(
            200,
            json={
                "data": {
                    "today": {"revenue": 1200, "profit": 300, "sales": 8}
                }
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(registry=_registry(), retailer=retailer)
            results = await executor.execute_reads(
                [
                    ToolCall(
                        id="1",
                        name="today_sale",
                        arguments={"storeId": STORE_ID},
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
            )
        assert results[0].success is True
        assert results[0].data == {
            "revenue": 1200,
            "profit": 300,
            "sales": 8,
        }

    asyncio.run(run())


def test_executor_maps_403_to_failed_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "No permission"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(registry=_registry(), retailer=retailer)
            results = await executor.execute_reads(
                [
                    ToolCall(
                        id="1",
                        name="stock_summary",
                        arguments={"storeId": STORE_ID},
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
            )
        assert results[0].success is False
        assert results[0].data == {
            "code": "TOOL_FORBIDDEN",
            "message": "No permission",
        }

    asyncio.run(run())


def test_executor_401_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(registry=_registry(), retailer=retailer)
            with pytest.raises(AppError) as exc_info:
                await executor.execute_reads(
                    [
                        ToolCall(
                            id="1",
                            name="payment_history",
                            arguments={"storeId": STORE_ID},
                        )
                    ],
                    access_token="token",
                    store_id=STORE_ID,
                )
        assert exc_info.value.code == "TOOL_UNAUTHORIZED"

    asyncio.run(run())
