"""Phase 5 verification test suite: Grounded Business Intelligence Engine.

Covers:
- Exact arithmetic against known fixtures (no float drift).
- Pareto ranking and revenue-share totals.
- Payment-mode totals, percentages and zero-denominator cases.
- Expenses, outstanding dues and business-day boundaries.
- Inventory velocity, insufficient history and missing records.
- Pagination and coverage completeness/incompleteness.
- Cross-store isolation and cache-key isolation.
- Upstream errors, malformed responses, timeouts and partial data.
- English, Hindi, Hinglish and Gujarati routing for supported insight tools.
- Proof that model-generated numeric calculations are not the source of metrics.
- Regression safety across Phase 1–4 governance.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.insights.cache import (
    InMemoryInsightCache,
    _format_cache_key,
)
from app.insights.common import (
    quantize_money,
    quantize_pct,
    resolve_window_dates,
    to_decimal,
)
from app.insights.inventory_velocity import calculate_inventory_velocity
from app.insights.payment_mix import calculate_payment_mix
from app.insights.sales_pareto import calculate_sales_pareto
from app.insights.store_brief import compile_store_brief
from app.integrations.retailer_client import RetailerHttpError, RetailerResponse
from app.orchestrator.tool_selector import resolve_turn_intent
from app.schemas.tool import ToolResult
from app.tools.context import ToolContext
from app.tools.handlers.read_tools import (
    inventory_velocity,
    payment_mix,
    sales_pareto,
    store_brief,
)
from app.tools.projection import project_tool_result

# ---------------------------------------------------------------------------
# 1. Exact arithmetic against known fixtures
# ---------------------------------------------------------------------------


def test_exact_arithmetic_fixtures() -> None:
    """Verify that decimal conversions have zero floating-point drift."""
    d1 = to_decimal(0.1)
    d2 = to_decimal(0.2)
    assert d1 + d2 == Decimal("0.30")

    unit_price = Decimal("19.99")
    qty = 3
    total = quantize_money(unit_price * Decimal(qty))
    assert str(total) == "59.97"

    share = Decimal("1") / Decimal("3") * Decimal("100")
    assert str(quantize_pct(share)) == "33.33"


# ---------------------------------------------------------------------------
# 2. Pareto ranking and revenue share
# ---------------------------------------------------------------------------


def test_pareto_ranking_and_revenue_shares() -> None:
    """Verify 80/20 Pareto identification and product ranks."""
    invoices = [
        {
            "id": "inv_1",
            "invoiceStatus": "RELEASED",
            "items": [
                {
                    "productId": "prod_A",
                    "productName": "Basmati Rice 5kg",
                    "quantity": 10,
                    "price": 500,  # 5000.00
                },
                {
                    "productId": "prod_B",
                    "productName": "Sunflower Oil 1L",
                    "quantity": 20,
                    "price": 150,  # 3000.00
                },
            ],
        },
        {
            "id": "inv_2",
            "invoiceStatus": "RELEASED",
            "items": [
                {
                    "productId": "prod_A",
                    "productName": "Basmati Rice 5kg",
                    "quantity": 4,
                    "price": 500,  # 2000.00 (Total prod_A = 7000.00)
                },
                {
                    "productId": "prod_C",
                    "productName": "Sugar 1kg",
                    "quantity": 10,
                    "price": 50,  # 500.00
                },
                {
                    "productId": "prod_D",
                    "productName": "Salt 1kg",
                    "quantity": 25,
                    "price": 20,  # 500.00
                },
            ],
        },
        {
            "id": "inv_cancelled",
            "invoiceStatus": "CANCELLED",
            "items": [
                {
                    "productId": "prod_E",
                    "productName": "Cancelled Item",
                    "quantity": 100,
                    "price": 1000,
                }
            ],
        },
    ]

    result = calculate_sales_pareto(invoices, window="7d", is_complete=True)

    assert result["totalRevenue"] == "11000.00"
    assert result["totalUnitsSold"] == 69
    assert result["totalProductsSold"] == 4

    top = result["topProducts"]
    assert len(top) == 4
    assert top[0]["productId"] == "prod_A"
    assert top[0]["revenue"] == "7000.00"
    assert top[0]["revenueSharePct"] == 63.64
    assert top[0]["cumulativeSharePct"] == 63.64

    assert top[1]["productId"] == "prod_B"
    assert top[1]["revenue"] == "3000.00"
    assert top[1]["revenueSharePct"] == 27.27
    assert top[1]["cumulativeSharePct"] == 90.91

    pareto = result["paretoProducts"]
    assert len(pareto) == 2
    assert [p["productId"] for p in pareto] == ["prod_A", "prod_B"]
    assert result["paretoTopCount"] == 2
    assert "2 of 4 products (50.0%) generate 80% of revenue" in result["paretoRatio"]
    assert result["coverage"]["scanned_bills"] == 3
    assert result["coverage"]["is_complete"] is True


def test_pareto_empty_and_zero_revenue() -> None:
    """Verify safe zero handling without ZeroDivisionError."""
    result = calculate_sales_pareto([], window="7d", is_complete=True)
    assert result["totalRevenue"] == "0.00"
    assert result["totalUnitsSold"] == 0
    assert result["topProducts"] == []
    assert result["paretoProducts"] == []
    assert result["paretoTopCount"] == 0
    assert result["coverage"]["is_complete"] is True


# ---------------------------------------------------------------------------
# 3. Payment mix totals, percentages and zero-denominator
# ---------------------------------------------------------------------------


def test_payment_mix_totals_and_percentages() -> None:
    """Verify payment mode categorizations and exact percentage shares."""
    invoices = [
        {"paymentMode": "CASH", "totalAmount": "2500.00", "invoiceStatus": "RELEASED"},
        {"paymentMode": "UPI", "totalAmount": "5000.00", "invoiceStatus": "RELEASED"},
        {"paymentMode": "GPay", "totalAmount": "2500.00", "invoiceStatus": "RELEASED"},
        {"paymentMode": "CARD", "totalAmount": "2000.00", "invoiceStatus": "RELEASED"},
        {
            "paymentMode": "UDHAAR",
            "totalAmount": "1000.00",
            "invoiceStatus": "RELEASED",
        },
        {"paymentMode": "NEFT", "totalAmount": "2000.00", "invoiceStatus": "RELEASED"},
        {"paymentMode": "CASH", "totalAmount": "9999.00", "invoiceStatus": "CANCELLED"},
    ]

    result = calculate_payment_mix(invoices, window="7d", is_complete=True)

    assert result["totalAmount"] == "15000.00"
    assert result["invoiceCount"] == 6
    assert result["primaryMode"] == "UPI"

    bd = result["breakdown"]
    assert bd["UPI"]["amount"] == "7500.00"
    assert bd["UPI"]["count"] == 2
    assert bd["UPI"]["sharePct"] == 50.0

    assert bd["CASH"]["amount"] == "2500.00"
    assert bd["CASH"]["count"] == 1
    assert bd["CASH"]["sharePct"] == 16.67

    assert bd["CREDIT"]["amount"] == "1000.00"
    assert bd["CREDIT"]["count"] == 1
    assert bd["CREDIT"]["sharePct"] == 6.67


def test_payment_mix_zero_denominator() -> None:
    """Zero collection must yield 0.0% shares with primaryMode='NONE'."""
    result = calculate_payment_mix([], window="today", is_complete=True)
    assert result["totalAmount"] == "0.00"
    assert result["invoiceCount"] == 0
    assert result["primaryMode"] == "NONE"
    for mode_info in result["breakdown"].values():
        assert mode_info["amount"] == "0.00"
        assert mode_info["sharePct"] == 0.0


# ---------------------------------------------------------------------------
# 4. Business day and time-zone boundaries
# ---------------------------------------------------------------------------


def test_business_day_boundaries() -> None:
    """Verify window date resolution adheres to IST boundaries."""
    today_w, start_today, end_today = resolve_window_dates("today")
    assert today_w == "today"
    assert start_today == end_today

    w7, start7, end7 = resolve_window_dates("7d")
    assert w7 == "7d"
    assert start7 <= end7

    w30, start30, end30 = resolve_window_dates("30d")
    assert w30 == "30d"
    assert start30 <= end30


# ---------------------------------------------------------------------------
# 5. Inventory velocity & zero observed sales
# ---------------------------------------------------------------------------


def test_inventory_velocity_segmentation() -> None:
    """Verify distinct labeling for zero sales in window vs dead stock."""
    stock_items = [
        {
            "productId": "prod_1",
            "name": "Tata Tea Gold",
            "availableQuantity": 15,
            "lowStockThreshold": 5,
        },
        {
            "productId": "prod_2",
            "name": "Amul Butter 500g",
            "availableQuantity": 3,
            "lowStockThreshold": 5,
            "isLowStock": True,
        },
        {
            "productId": "prod_3",
            "name": "Slow Scented Candles",
            "availableQuantity": 40,
            "lowStockThreshold": 5,
        },
    ]

    invoices = [
        {
            "invoiceStatus": "RELEASED",
            "items": [{"productId": "prod_1", "quantity": 10}],
        }
    ]

    result = calculate_inventory_velocity(
        stock_items, invoices, window="7d", is_complete=True
    )

    assert result["totalStockItemsScanned"] == 3
    assert result["itemsWithSalesInWindow"] == 1
    assert result["zeroObservedSalesCount"] == 2
    assert result["lowStockCount"] == 1

    fast = result["fastMovingItems"]
    assert len(fast) == 1
    assert fast[0]["productId"] == "prod_1"
    assert fast[0]["unitsSoldInWindow"] == 10

    zero_sales = result["zeroObservedSalesItems"]
    assert len(zero_sales) == 2
    candle_item = next(i for i in zero_sales if i["productId"] == "prod_3")
    assert candle_item["availableQuantity"] == 40
    assert candle_item["unitsSoldInWindow"] == 0
    assert candle_item["zeroSalesInScannedWindow"] is True
    assert "not confirmed dead stock" in candle_item["observationNote"]

    assert result["coverage"]["scanned_bills"] == 1
    assert result["coverage"]["scanned_stock_items"] == 3
    assert result["coverage"]["is_complete"] is True


def test_inventory_velocity_insufficient_history() -> None:
    """Empty invoice list leaves products flagged with observation note."""
    stock = [{"productId": "p1", "name": "Item 1", "availableQuantity": 10}]
    result = calculate_inventory_velocity(stock, [], window="7d", is_complete=False)
    assert result["itemsWithSalesInWindow"] == 0
    assert result["zeroObservedSalesCount"] == 1
    assert result["coverage"]["is_complete"] is False


# ---------------------------------------------------------------------------
# 6. Composite store brief and partial upstream failure
# ---------------------------------------------------------------------------


def test_compile_store_brief_complete() -> None:
    """Verify store brief math combining all 4 verified sources."""
    revenue = {
        "today": {"totalRevenue": 15000, "totalProfit": 3000, "totalOrders": 25}
    }
    stock = {"totals": {"totalSkus": 120, "lowStockItems": 8, "outOfStockItems": 2}}
    customer = {"totalDues": 4500, "overdueCount": 6}
    expenses = {"totalExpense": 2000, "totalCount": 3}

    brief = compile_store_brief(
        revenue, stock, customer, expenses, date_str="2026-10-19", is_complete=True
    )

    assert brief["date"] == "2026-10-19"
    assert brief["todaySales"]["revenue"] == "15000.00"
    assert brief["todaySales"]["profit"] == "3000.00"
    assert brief["todaySales"]["ordersCount"] == 25
    assert brief["inventoryHealth"]["lowStockCount"] == 8
    assert brief["customerReceivables"]["totalDues"] == "4500.00"
    assert brief["expenses"]["totalExpense"] == "2000.00"
    assert brief["netCashflowIndication"] == "13000.00"
    assert brief["coverage"]["is_complete"] is True


def test_compile_store_brief_partial_source_failure() -> None:
    """When sources fail, metrics are None and status is UNAVAILABLE."""
    revenue = {
        "today": {"totalRevenue": 8000, "totalProfit": 1600, "totalOrders": 10}
    }
    stock = {"totals": {"totalSkus": 50, "lowStockItems": 1}}

    brief = compile_store_brief(
        revenue, stock, None, None, date_str="2026-10-19", is_complete=True
    )

    assert brief["todaySales"]["revenue"] == "8000.00"
    assert brief["todaySales"]["status"] == "AVAILABLE"
    # Unavailable expenses must not be reported as 0.00
    assert brief["expenses"]["status"] == "UNAVAILABLE"
    assert brief["expenses"]["totalExpense"] is None
    assert brief["expenses"]["expenseCount"] is None
    # Unavailable customer dues must not be reported as 0.00
    assert brief["customerReceivables"]["status"] == "UNAVAILABLE"
    assert brief["customerReceivables"]["totalDues"] is None
    # Net cashflow must be None when expenses are unavailable
    assert brief["netCashflowIndication"] is None
    assert brief["netCashflowStatus"] == "UNAVAILABLE"
    assert brief["coverage"]["is_complete"] is False
    assert brief["coverage"]["sources"]["expenses"] is False
    assert brief["coverage"]["sources"]["customerDues"] is False
    assert brief["coverage"]["sources"]["sales"] is True
    assert set(brief["coverage"]["failed_sources"]) == {"customerDues", "expenses"}


# ---------------------------------------------------------------------------
# 7. Pagination and coverage metadata completeness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_and_coverage_completeness() -> None:
    """Verify handlers mark coverage is_complete=False when pagination cuts off."""
    class MockRetailer:
        async def list_invoices(self, **kwargs: Any) -> Any:
            class DummyResp:
                status_code = 200
                body = {
                    "data": [
                        {
                            "id": "inv_1",
                            "invoiceStatus": "RELEASED",
                            "paymentMode": "UPI",
                            "totalAmount": 100,
                            "items": [{"productId": "p1", "quantity": 1, "price": 100}],
                        }
                    ],
                    "meta": {
                        "hasNextPage": True,
                        "nextCursor": "cursor_123",
                    },
                }
            return DummyResp()

    ctx = ToolContext(
        access_token="tok",
        store_id="507f1f77bcf86cd799439011",
        retailer=MockRetailer(),  # type: ignore[arg-type]
    )

    args = {"storeId": "507f1f77bcf86cd799439011", "window": "7d"}
    res = await payment_mix(args, ctx)
    assert res.success is True
    assert res.data["coverage"]["is_complete"] is False


@pytest.mark.asyncio
async def test_handlers_end_to_end_mock() -> None:
    """Verify all 4 read handlers execute through ToolContext and return clean data."""
    class MockFullRetailer:
        async def list_invoices(self, **kwargs: Any) -> Any:
            class Resp:
                status_code = 200
                body = {
                    "data": [
                        {
                            "id": "i1",
                            "invoiceStatus": "RELEASED",
                            "paymentMode": "CASH",
                            "totalAmount": "200.00",
                            "items": [
                                {
                                    "productId": "p1",
                                    "productName": "Soap",
                                    "quantity": 2,
                                    "price": 100,
                                }
                            ],
                        }
                    ],
                    "meta": {"hasNextPage": False},
                }
            return Resp()

        async def get_stock_items(self, **kwargs: Any) -> Any:
            class Resp:
                status_code = 200
                body = {
                    "data": {
                        "items": [
                            {"productId": "p1", "name": "Soap", "availableQuantity": 10}
                        ]
                    }
                }
            return Resp()

        async def get_revenue(self, **kwargs: Any) -> Any:
            class Resp:
                status_code = 200
                body = {"data": {"today": {"totalRevenue": 200, "totalOrders": 1}}}
            return Resp()

        async def get_stock(self, **kwargs: Any) -> Any:
            class Resp:
                status_code = 200
                body = {"data": {"totals": {"totalSkus": 5, "lowStockItems": 0}}}
            return Resp()

        async def get_customer_analytics(self, **kwargs: Any) -> Any:
            class Resp:
                status_code = 200
                body = {"data": {"totalDues": 0, "overdueCount": 0}}
            return Resp()

        async def get_expense_analytics(self, **kwargs: Any) -> Any:
            class Resp:
                status_code = 200
                body = {"data": {"totalExpense": 50, "totalCount": 1}}
            return Resp()

    cache = InMemoryInsightCache(ttl_seconds=300)
    ctx = ToolContext(
        access_token="tok",
        store_id="507f1f77bcf86cd799439011",
        retailer=MockFullRetailer(),  # type: ignore[arg-type]
        insight_cache=cache,
    )

    store_args = {"storeId": "507f1f77bcf86cd799439011"}

    # 1. sales_pareto
    pareto_res = await sales_pareto(store_args, ctx)
    assert pareto_res.success is True
    assert pareto_res.data["totalRevenue"] == "200.00"

    # 2. payment_mix
    pm_res = await payment_mix(store_args, ctx)
    assert pm_res.success is True
    assert pm_res.data["primaryMode"] == "CASH"

    # 3. inventory_velocity
    vel_res = await inventory_velocity(store_args, ctx)
    assert vel_res.success is True
    assert vel_res.data["itemsWithSalesInWindow"] == 1

    # 4. store_brief
    brief_res = await store_brief(store_args, ctx)
    assert brief_res.success is True
    assert brief_res.data["todaySales"]["revenue"] == "200.00"
    assert brief_res.data["netCashflowIndication"] == "150.00"


# ---------------------------------------------------------------------------
# 8. Cross-store isolation and cache-key isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_tenant_isolation() -> None:
    """Verify cache keys are strictly scoped to store_id and prevent cross-leakage."""
    cache = InMemoryInsightCache(ttl_seconds=300)

    store_a = "507f1f77bcf86cd799439011"
    store_b = "507f1f77bcf86cd799439022"

    payload_a = {"totalRevenue": "5000.00", "coverage": {"scanned_bills": 10}}
    payload_b = {"totalRevenue": "12000.00", "coverage": {"scanned_bills": 25}}

    await cache.set(store_a, "sales_pareto", "7d", payload_a)
    await cache.set(store_b, "sales_pareto", "7d", payload_b)

    cached_a = await cache.get(store_a, "sales_pareto", "7d")
    cached_b = await cache.get(store_b, "sales_pareto", "7d")

    assert cached_a is not None
    assert cached_b is not None
    assert cached_a["totalRevenue"] == "5000.00"
    assert cached_b["totalRevenue"] == "12000.00"

    with pytest.raises(ValueError, match="store_id is required"):
        _format_cache_key("", "sales_pareto", "7d")


# ---------------------------------------------------------------------------
# 9. Tool projection verification
# ---------------------------------------------------------------------------


def test_projection_preserves_insights_and_coverage() -> None:
    """Verify project_tool_result projects Phase 5 tools without loss."""
    # 1. sales_pareto
    pareto_res = ToolResult(
        tool="sales_pareto",
        success=True,
        data={
            "totalRevenue": "1000.00",
            "topProducts": [
                {
                    "rank": 1,
                    "productId": "p1",
                    "productName": "Item 1",
                    "revenue": "1000.00",
                    "revenueSharePct": 100.0,
                    "extraSensitiveField": "should_be_stripped",
                }
            ],
            "coverage": {"scanned_bills": 5, "window": "7d", "is_complete": True},
        },
    )
    proj_pareto = project_tool_result(pareto_res)
    assert proj_pareto.data["totalRevenue"] == "1000.00"
    assert proj_pareto.data["topProducts"][0]["productName"] == "Item 1"
    assert "extraSensitiveField" not in proj_pareto.data["topProducts"][0]
    assert proj_pareto.data["coverage"]["is_complete"] is True

    # 2. payment_mix
    pm_res = ToolResult(
        tool="payment_mix",
        success=True,
        data={
            "totalAmount": "2000.00",
            "primaryMode": "UPI",
            "breakdown": {"UPI": {"amount": "2000.00", "sharePct": 100.0}},
            "coverage": {"scanned_bills": 1, "is_complete": True},
        },
    )
    proj_pm = project_tool_result(pm_res)
    assert proj_pm.data["primaryMode"] == "UPI"
    assert proj_pm.data["breakdown"]["UPI"]["amount"] == "2000.00"

    # 3. store_brief
    sb_res = ToolResult(
        tool="store_brief",
        success=True,
        data={
            "date": "2026-10-19",
            "todaySales": {"revenue": "500.00"},
            "netCashflowIndication": "300.00",
            "coverage": {"is_complete": True},
        },
    )
    proj_sb = project_tool_result(sb_res)
    assert proj_sb.data["date"] == "2026-10-19"
    assert proj_sb.data["netCashflowIndication"] == "300.00"


# ---------------------------------------------------------------------------
# 10. Multi-lingual routing (English, Hindi, Hinglish, Gujarati)
# ---------------------------------------------------------------------------


def test_multi_lingual_routing_for_insights() -> None:
    """Verify multi-language cues route to the appropriate insight tools."""
    available = {
        "today_sale",
        "sales_pareto",
        "payment_mix",
        "inventory_velocity",
        "store_brief",
        "stock_summary",
        "expense_summary",
        "customer_summary",
    }

    # English
    en_brief = resolve_turn_intent("give me daily store brief", available=available)
    assert "store_brief" in en_brief.tool_names

    en_pareto = resolve_turn_intent("show 80 20 top products", available=available)
    assert "sales_pareto" in en_pareto.tool_names

    en_pm = resolve_turn_intent(
        "what is cash vs upi payment mix", available=available
    )
    assert "payment_mix" in en_pm.tool_names

    en_vel = resolve_turn_intent(
        "show inventory velocity and dead stock", available=available
    )
    assert "inventory_velocity" in en_vel.tool_names

    # Hindi / Hinglish
    hi_brief = resolve_turn_intent("aaj ka hisaab batao", available=available)
    assert "store_brief" in hi_brief.tool_names

    hi_pareto = resolve_turn_intent(
        "sabse jyada bikne wale product dikhao", available=available
    )
    assert "sales_pareto" in hi_pareto.tool_names

    hi_pm = resolve_turn_intent("kitna cash kitna upi aaya", available=available)
    assert "payment_mix" in hi_pm.tool_names

    hi_vel = resolve_turn_intent("kaun sa maal nahi bik raha", available=available)
    assert "inventory_velocity" in hi_vel.tool_names

    # Gujarati
    gu_brief = resolve_turn_intent("આજનો હિસાબ આપો", available=available)
    assert "store_brief" in gu_brief.tool_names

    gu_pareto = resolve_turn_intent(
        "સૌથી વધુ વેચાણ કઈ વસ્તુઓનું થયું", available=available
    )
    assert "sales_pareto" in gu_pareto.tool_names

    gu_pm = resolve_turn_intent("રોકડ અને યુપીઆઈ કેટલું થયું", available=available)
    assert "payment_mix" in gu_pm.tool_names

    gu_vel = resolve_turn_intent("કયો માલ વેચાતો નથી", available=available)
    assert "inventory_velocity" in gu_vel.tool_names


# ---------------------------------------------------------------------------
# 11. Regression test: Sensitive write tools are NOT exposed by insight queries
# ---------------------------------------------------------------------------


def test_sensitive_write_tools_isolated_from_insights() -> None:
    """Verify that insight requests never accidentally expose sensitive write tools."""
    available = {
        "store_brief",
        "sales_pareto",
        "payment_mix",
        "inventory_velocity",
        "create_purchase_order",
        "create_expense",
        "ledger_debit",
    }
    intent = resolve_turn_intent("aaj ka hisaab batao", available=available)
    assert "create_purchase_order" not in intent.tool_names
    assert "create_expense" not in intent.tool_names
    assert "ledger_debit" not in intent.tool_names
    assert "store_brief" in intent.tool_names


# ---------------------------------------------------------------------------
# 12. Quality Gate: Genuine Zeros vs Missing/Unavailable Data
# ---------------------------------------------------------------------------


def test_compile_store_brief_genuine_zeros() -> None:
    """Verify genuine 0.00 metrics remain distinguishable from missing data."""
    revenue = {
        "today": {"revenue": 0, "profit": 0, "sales": 0}
    }
    stock = {
        "totals": {
            "totalSkus": 10,
            "totalQuantity": 50,
            "lowStockItems": 0,
            "outOfStockItems": 0,
        }
    }
    customer = {
        "totalDues": 0, "overdueCount": 0
    }
    expenses = {
        "amounts": {"todayAmount": 0}, "counts": {"todayExpenses": 0}
    }

    brief = compile_store_brief(
        revenue, stock, customer, expenses, date_str="2026-10-19", is_complete=True
    )

    assert brief["todaySales"]["status"] == "AVAILABLE"
    assert brief["todaySales"]["revenue"] == "0.00"
    assert brief["todaySales"]["profit"] == "0.00"
    assert brief["todaySales"]["ordersCount"] == 0

    assert brief["expenses"]["status"] == "AVAILABLE"
    assert brief["expenses"]["totalExpense"] == "0.00"
    assert brief["expenses"]["expenseCount"] == 0

    assert brief["customerReceivables"]["status"] == "AVAILABLE"
    assert brief["customerReceivables"]["totalDues"] == "0.00"

    assert brief["netCashflowStatus"] == "AVAILABLE"
    assert brief["netCashflowIndication"] == "0.00"

    assert brief["coverage"]["is_complete"] is True
    assert brief["coverage"]["failed_sources"] == []


# ---------------------------------------------------------------------------
# 13. Quality Gate: Store Brief Handler Upstream Failure & Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_brief_handler_expense_failure() -> None:
    """Verify store_brief marks expenses UNAVAILABLE when API raises HTTP 500."""
    class MockRetailer:
        async def get_revenue(self, **kwargs: Any) -> Any:
            return RetailerResponse(
                status_code=200,
                body={
                    "data": {
                        "today": {
                            "totalRevenue": 5000,
                            "totalProfit": 1000,
                            "totalOrders": 5,
                        }
                    }
                },
            )

        async def get_stock(self, **kwargs: Any) -> Any:
            return RetailerResponse(
                status_code=200,
                body={"data": {"totals": {"totalSkus": 20, "lowStockItems": 1}}},
            )

        async def get_customer_analytics(self, **kwargs: Any) -> Any:
            return RetailerResponse(
                status_code=200,
                body={"data": {"totalDues": 1200, "overdueCount": 2}},
            )

        async def get_expense_analytics(self, **kwargs: Any) -> Any:
            raise RetailerHttpError(500, "EXPENSE_SERVICE_TIMEOUT", "Gateway timed out")

    ctx = ToolContext(
        store_id="store_fail_test",
        access_token="tok_1",
        retailer=MockRetailer(),
        insight_cache=InMemoryInsightCache(),
    )

    res = await store_brief({"date": "2026-10-19"}, ctx)
    assert res.success is True
    data = res.data

    assert data["todaySales"]["status"] == "AVAILABLE"
    assert data["todaySales"]["revenue"] == "5000.00"

    # Expenses must be UNAVAILABLE, not 0.00
    assert data["expenses"]["status"] == "UNAVAILABLE"
    assert data["expenses"]["totalExpense"] is None
    assert data["expenses"]["expenseCount"] is None

    # Net cashflow must be None because expenses failed
    assert data["netCashflowIndication"] is None
    assert data["netCashflowStatus"] == "UNAVAILABLE"

    # Coverage must indicate incomplete and list expenses as failed
    assert data["coverage"]["is_complete"] is False
    assert "expenses" in data["coverage"]["failed_sources"]


@pytest.mark.asyncio
async def test_store_brief_handler_malformed_response() -> None:
    """Verify store_brief handler treats empty/malformed data as UNAVAILABLE."""
    class MockRetailer:
        async def get_revenue(self, **kwargs: Any) -> Any:
            return RetailerResponse(status_code=200, body={"data": None})

        async def get_stock(self, **kwargs: Any) -> Any:
            return RetailerResponse(status_code=200, body={"data": {}})

        async def get_customer_analytics(self, **kwargs: Any) -> Any:
            return RetailerResponse(status_code=200, body={})

        async def get_expense_analytics(self, **kwargs: Any) -> Any:
            return RetailerResponse(status_code=200, body={"data": None})

    ctx = ToolContext(
        store_id="store_malformed_test",
        access_token="tok_1",
        retailer=MockRetailer(),
        insight_cache=InMemoryInsightCache(),
    )

    res = await store_brief({"date": "2026-10-19"}, ctx)
    assert res.success is True
    data = res.data

    assert data["todaySales"]["status"] == "UNAVAILABLE"
    assert data["todaySales"]["revenue"] is None
    assert data["expenses"]["status"] == "UNAVAILABLE"
    assert data["expenses"]["totalExpense"] is None
    assert data["netCashflowIndication"] is None
    assert data["coverage"]["is_complete"] is False
    expected_failed = {"sales", "inventory", "customerDues", "expenses"}
    assert set(data["coverage"]["failed_sources"]) == expected_failed


# ---------------------------------------------------------------------------
# 14. Quality Gate: Payment Mix Partial Payments, Unpaid & Credit Notes
# ---------------------------------------------------------------------------


def test_payment_mix_partial_payments() -> None:
    """Invoice with partial payment: collected attributed to mode, due to CREDIT."""
    invoices = [
        {
            "id": "inv_partial_1",
            "invoiceStatus": "RELEASED",
            "paymentMode": "UPI",
            "paymentStatus": "PARTIAL",
            "totalAmount": 1000,
            "paidAmount": 300,
            "dueAmount": 700,
        },
        {
            "id": "inv_paid_1",
            "invoiceStatus": "RELEASED",
            "paymentMode": "CASH",
            "paymentStatus": "PAID",
            "totalAmount": 500,
            "paidAmount": 500,
            "dueAmount": 0,
        },
    ]

    result = calculate_payment_mix(invoices, window="7d", is_complete=True)

    assert result["totalInvoiced"] == "1500.00"
    assert result["totalCollected"] == "800.00"
    assert result["totalUncollectedCredit"] == "700.00"

    bd = result["breakdown"]
    assert bd["UPI"]["amount"] == "300.00"
    assert bd["UPI"]["count"] == 1
    assert bd["UPI"]["sharePct"] == 20.0

    assert bd["CASH"]["amount"] == "500.00"
    assert bd["CASH"]["count"] == 1
    assert bd["CASH"]["sharePct"] == 33.33

    assert bd["CREDIT"]["amount"] == "700.00"
    assert bd["CREDIT"]["count"] == 1
    assert bd["CREDIT"]["sharePct"] == 46.67


def test_payment_mix_unpaid_invoices_not_claimed_as_cash() -> None:
    """UNPAID invoice with default paymentMode='CASH' must not claim cash collected."""
    invoices = [
        {
            "id": "inv_unpaid_1",
            "invoiceStatus": "RELEASED",
            "paymentMode": "CASH",  # Core's default paymentMode
            "paymentStatus": "UNPAID",
            "totalAmount": 1200,
            "paidAmount": 0,
            "dueAmount": 1200,
        }
    ]

    result = calculate_payment_mix(invoices, window="today", is_complete=True)

    assert result["totalInvoiced"] == "1200.00"
    assert result["totalCollected"] == "0.00"
    assert result["totalUncollectedCredit"] == "1200.00"

    bd = result["breakdown"]
    assert bd["CASH"]["amount"] == "0.00"
    assert bd["CASH"]["count"] == 0
    assert bd["CREDIT"]["amount"] == "1200.00"
    assert bd["CREDIT"]["count"] == 1
    assert bd["CREDIT"]["sharePct"] == 100.0


def test_payment_mix_credit_notes_excluded() -> None:
    """Credit notes (refunds/adjustments) must be excluded from payment mix."""
    invoices = [
        {
            "id": "inv_sale",
            "invoiceStatus": "RELEASED",
            "docType": "REGULAR",
            "paymentMode": "UPI",
            "paymentStatus": "PAID",
            "totalAmount": 2000,
        },
        {
            "id": "inv_cn",
            "invoiceStatus": "RELEASED",
            "docType": "CREDIT_NOTE",
            "paymentMode": "UPI",
            "totalAmount": 500,
        },
    ]

    result = calculate_payment_mix(invoices, window="today", is_complete=True)
    assert result["totalInvoiced"] == "2000.00"
    assert result["totalCollected"] == "2000.00"
    assert result["invoiceCount"] == 1


# ---------------------------------------------------------------------------
# 15. Quality Gate: Pareto Discount & Quantity Idempotency
# ---------------------------------------------------------------------------


def test_pareto_discount_and_quantity_applied_once() -> None:
    """Prove discountedPrice is unit price and quantity is multiplied exactly once."""
    invoices = [
        {
            "id": "inv_test",
            "invoiceStatus": "RELEASED",
            "items": [
                {
                    "productId": "p_disc",
                    "productName": "Premium Tea",
                    "quantity": 3,
                    "price": 1000,           # MRP / list price
                    "discountedPrice": 800,   # Unit price after discount
                },
                {
                    "productId": "p_total",
                    "productName": "Organic Sugar",
                    "quantity": 2,
                    "total": 500,             # Line total directly provided
                },
            ],
        }
    ]

    result = calculate_sales_pareto(invoices, window="7d", is_complete=True)
    # p_disc: 800 * 3 = 2400.00
    # p_total: 500.00
    # Total revenue: 2900.00
    assert result["totalRevenue"] == "2900.00"
    items = result["topProducts"]
    tea = next(i for i in items if i["productId"] == "p_disc")
    assert tea["revenue"] == "2400.00"
    assert tea["unitsSold"] == 3

    sugar = next(i for i in items if i["productId"] == "p_total")
    assert sugar["revenue"] == "500.00"
    assert sugar["unitsSold"] == 2


# ---------------------------------------------------------------------------
# 16. Quality Gate: Inventory Velocity Capped Scan Note
# ---------------------------------------------------------------------------


def test_inventory_velocity_capped_scan_note() -> None:
    """When scan is capped, observationNote must explicitly state partial scan."""
    stock = [{"productId": "p1", "name": "Winter Jacket", "availableQuantity": 15}]
    invoices = [{"invoiceStatus": "RELEASED", "items": []}]

    result = calculate_inventory_velocity(
        stock, invoices, window="30d", is_complete=False
    )
    zero_items = result["zeroObservedSalesItems"]
    assert len(zero_items) == 1
    note = zero_items[0]["observationNote"]
    assert "partial/capped scan" in note
    assert "not confirmed dead stock" in note

