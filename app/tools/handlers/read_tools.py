from __future__ import annotations

from typing import Any

from app.integrations.retailer_client import RetailerHttpError
from app.schemas.tool import ToolResult
from app.tools.context import ToolContext


async def search_product(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_products(
            access_token=context.access_token,
            store_id=arguments["storeId"],
            query=arguments["query"],
        )
    except RetailerHttpError as exc:
        return _failure("search_product", exc)

    body = response.body
    data: dict[str, Any] = {"items": body.get("data") or []}
    if body.get("pagination") is not None:
        data["pagination"] = body["pagination"]
    return ToolResult(tool="search_product", success=True, data=data)


async def today_sale(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_revenue(
            access_token=context.access_token,
            store_id=arguments["storeId"],
        )
    except RetailerHttpError as exc:
        return _failure("today_sale", exc)

    payload = response.body.get("data") or {}
    today = payload.get("today") if isinstance(payload, dict) else None
    return ToolResult(
        tool="today_sale",
        success=True,
        data=today if isinstance(today, dict) else {},
    )


async def stock_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_stock(
            access_token=context.access_token,
            store_id=arguments["storeId"],
        )
    except RetailerHttpError as exc:
        return _failure("stock_summary", exc)

    payload = response.body.get("data") or {}
    data: dict[str, Any] = {}
    if isinstance(payload, dict):
        if isinstance(payload.get("totals"), dict):
            data["totals"] = payload["totals"]
        if isinstance(payload.get("valueSummary"), dict):
            data["valueSummary"] = payload["valueSummary"]
    return ToolResult(tool="stock_summary", success=True, data=data)


async def search_customer(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_customers(
            access_token=context.access_token,
            store_id=arguments["storeId"],
            query=arguments["query"],
        )
    except RetailerHttpError as exc:
        return _failure("search_customer", exc)

    raw_items = response.body.get("data") or []
    # Compact projection: enough for the LLM to pick a real id without
    # dumping full customer PII into the context window. Contract:
    # GET /customer runs customerSerializer, which exposes `id`.
    items = [
        {
            "id": str(item.get("id") or ""),
            "name": item.get("name"),
            "phone": item.get("phone"),
            "email": item.get("email"),
        }
        for item in raw_items
        if isinstance(item, dict)
    ]
    return ToolResult(
        tool="search_customer",
        success=True,
        data={"items": items},
    )


async def payment_history(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_payments(
            access_token=context.access_token,
            store_id=arguments["storeId"],
        )
    except RetailerHttpError as exc:
        return _failure("payment_history", exc)

    body = response.body
    data: dict[str, Any] = {"items": body.get("data") or []}
    if body.get("pagination") is not None:
        data["pagination"] = body["pagination"]
    return ToolResult(tool="payment_history", success=True, data=data)


def _failure(tool: str, exc: RetailerHttpError) -> ToolResult:
    return ToolResult(
        tool=tool,
        success=False,
        data={"code": exc.code, "message": exc.message},
    )


READ_TOOL_HANDLERS = {
    "search_product": search_product,
    "today_sale": today_sale,
    "stock_summary": stock_summary,
    "search_customer": search_customer,
    "payment_history": payment_history,
}
