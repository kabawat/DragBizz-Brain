"""Deterministic composite store brief (daily health snapshot) engine.

Combines live sales, stock levels, receivables, and expenses in pure Python.
Zero LLM calculation. All currency arithmetic uses Decimal precision.
Explicitly distinguishes missing/failed upstream sources from genuine zeros.
"""

from __future__ import annotations

from typing import Any

from app.insights.common import quantize_money, to_decimal


def compile_store_brief(
    today_revenue: dict[str, Any] | None,
    stock_totals: dict[str, Any] | None,
    customer_totals: dict[str, Any] | None,
    expense_totals: dict[str, Any] | None,
    *,
    date_str: str,
    is_complete: bool = True,
) -> dict[str, Any]:
    """Compile composite store brief from verified source payloads.

    Unavailable sources are represented explicitly with status='UNAVAILABLE'
    and None metrics, never substituted with fabricated zeros.
    """
    sources_available = {
        "sales": isinstance(today_revenue, dict) and bool(today_revenue),
        "inventory": isinstance(stock_totals, dict) and bool(stock_totals),
        "customerDues": isinstance(customer_totals, dict) and bool(customer_totals),
        "expenses": isinstance(expense_totals, dict) and bool(expense_totals),
    }

    # 1. Sales today
    if sources_available["sales"]:
        rev_payload = today_revenue or {}
        today_raw = rev_payload.get("today")
        today_data = today_raw if isinstance(today_raw, dict) else rev_payload
        revenue_dec = to_decimal(
            today_data.get("totalRevenue") or today_data.get("revenue") or 0
        )
        profit_dec = to_decimal(
            today_data.get("totalProfit") or today_data.get("profit") or 0
        )
        raw_orders = today_data.get("totalOrders") or today_data.get("orderCount") or 0
        try:
            orders_count: int | None = int(raw_orders)
        except (ValueError, TypeError):
            orders_count = 0
        sales_section: dict[str, Any] = {
            "status": "AVAILABLE",
            "revenue": str(quantize_money(revenue_dec)),
            "profit": str(quantize_money(profit_dec)),
            "ordersCount": orders_count,
        }
    else:
        revenue_dec = None
        sales_section = {
            "status": "UNAVAILABLE",
            "revenue": None,
            "profit": None,
            "ordersCount": None,
        }

    # 2. Inventory health
    if sources_available["inventory"]:
        stk_payload = stock_totals or {}
        stk_raw = stk_payload.get("totals")
        stk_data = stk_raw if isinstance(stk_raw, dict) else stk_payload
        try:
            total_skus: int | None = int(
                stk_data.get("totalSkus") or stk_data.get("totalProducts") or 0
            )
        except (ValueError, TypeError):
            total_skus = 0
        try:
            total_qty: int | None = int(
                stk_data.get("totalQuantity") or stk_data.get("availableQuantity") or 0
            )
        except (ValueError, TypeError):
            total_qty = 0
        try:
            low_stock_count: int | None = int(
                stk_data.get("lowStockItems") or stk_data.get("lowStockCount") or 0
            )
        except (ValueError, TypeError):
            low_stock_count = 0
        try:
            out_of_stock_count: int | None = int(
                stk_data.get("outOfStockItems") or stk_data.get("outOfStockCount") or 0
            )
        except (ValueError, TypeError):
            out_of_stock_count = 0
        inventory_section: dict[str, Any] = {
            "status": "AVAILABLE",
            "totalSkus": total_skus,
            "totalQuantity": total_qty,
            "lowStockCount": low_stock_count,
            "outOfStockCount": out_of_stock_count,
        }
    else:
        inventory_section = {
            "status": "UNAVAILABLE",
            "totalSkus": None,
            "totalQuantity": None,
            "lowStockCount": None,
            "outOfStockCount": None,
        }

    # 3. Customer receivables / dues
    if sources_available["customerDues"]:
        cust_payload = customer_totals or {}
        dues_dec = to_decimal(
            cust_payload.get("totalDues")
            or cust_payload.get("totalReceivables")
            or cust_payload.get("outstandingDues")
            or 0
        )
        raw_debtors = (
            cust_payload.get("overdueCount")
            or cust_payload.get("customersWithDues")
            or 0
        )
        try:
            customers_with_dues: int | None = int(raw_debtors)
        except (ValueError, TypeError):
            customers_with_dues = 0
        customer_section: dict[str, Any] = {
            "status": "AVAILABLE",
            "totalDues": str(quantize_money(dues_dec)),
            "customersWithDues": customers_with_dues,
        }
    else:
        customer_section = {
            "status": "UNAVAILABLE",
            "totalDues": None,
            "customersWithDues": None,
        }

    # 4. Expenses
    if sources_available["expenses"]:
        exp_payload = expense_totals or {}
        amounts = (
            exp_payload.get("amounts")
            if isinstance(exp_payload.get("amounts"), dict)
            else exp_payload
        )
        counts = (
            exp_payload.get("counts")
            if isinstance(exp_payload.get("counts"), dict)
            else exp_payload
        )
        raw_exp_amount = (
            amounts.get("todayAmount")
            if amounts.get("todayAmount") is not None
            else (
                amounts.get("totalExpense")
                if amounts.get("totalExpense") is not None
                else amounts.get("total")
                if amounts.get("total") is not None
                else amounts.get("totalAmount")
                if amounts.get("totalAmount") is not None
                else 0
            )
        )
        expense_dec = to_decimal(raw_exp_amount)
        raw_exp_count = (
            counts.get("todayExpenses")
            if counts.get("todayExpenses") is not None
            else (
                counts.get("totalExpenses")
                if counts.get("totalExpenses") is not None
                else counts.get("totalCount")
                if counts.get("totalCount") is not None
                else counts.get("count")
                if counts.get("count") is not None
                else 0
            )
        )
        try:
            expense_count: int | None = int(raw_exp_count)
        except (ValueError, TypeError):
            expense_count = 0
        expense_section: dict[str, Any] = {
            "status": "AVAILABLE",
            "totalExpense": str(quantize_money(expense_dec)),
            "expenseCount": expense_count,
        }
    else:
        expense_dec = None
        expense_section = {
            "status": "UNAVAILABLE",
            "totalExpense": None,
            "expenseCount": None,
        }

    # 5. Net cashflow indication (Revenue - Expenses)
    if revenue_dec is not None and expense_dec is not None:
        net_indication = str(quantize_money(revenue_dec - expense_dec))
        net_status = "AVAILABLE"
    else:
        net_indication = None
        net_status = "UNAVAILABLE"

    failed_sources = [k for k, v in sources_available.items() if not v]
    effective_complete = is_complete and not failed_sources

    return {
        "date": date_str,
        "todaySales": sales_section,
        "inventoryHealth": inventory_section,
        "customerReceivables": customer_section,
        "expenses": expense_section,
        "netCashflowIndication": net_indication,
        "netCashflowStatus": net_status,
        "coverage": {
            "date": date_str,
            "window": "today",
            "is_complete": effective_complete,
            "sources": sources_available,
            "failed_sources": failed_sources,
        },
    }
