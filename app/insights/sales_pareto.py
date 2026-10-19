"""Deterministic 80/20 Pareto sales analysis calculation engine.

Identifies the vital few products that generate ~80% of store sales revenue.
Strictly pure Python: ZERO LLM math. All calculations use Decimal precision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.insights.common import (
    CoverageMetadata,
    quantize_money,
    quantize_pct,
    to_decimal,
)


def _is_valid_released_invoice(invoice: dict[str, Any]) -> bool:
    """Filter out non-RELEASED, draft, or cancelled invoices."""
    status = str(invoice.get("invoiceStatus") or "").upper().strip()
    if status and status != "RELEASED":
        return False
    if invoice.get("cancelledAt") or invoice.get("cancellationReason"):
        return False
    doc_type = str(invoice.get("docType") or invoice.get("invoiceType") or "").upper()
    return doc_type != "CREDIT_NOTE"


def _extract_item_revenue(item: dict[str, Any]) -> tuple[Decimal, int]:
    """Extract line revenue and quantity from an invoice line item."""
    raw_qty = item.get("quantity")
    try:
        qty = int(raw_qty) if raw_qty is not None else 1
    except (ValueError, TypeError):
        qty = 1
    if qty <= 0:
        return Decimal("0.00"), 0

    discounted_price = item.get("discountedPrice")
    price = item.get("price")
    selling_price = item.get("sellingPrice")
    product_obj = item.get("product")
    if isinstance(product_obj, dict) and price is None:
        price = product_obj.get("sellingPrice") or product_obj.get("price")

    chosen_unit_price: Any = None
    if discounted_price is not None and to_decimal(discounted_price) > Decimal("0.00"):
        chosen_unit_price = discounted_price
    elif price is not None and to_decimal(price) > Decimal("0.00"):
        chosen_unit_price = price
    elif selling_price is not None and to_decimal(selling_price) > Decimal("0.00"):
        chosen_unit_price = selling_price
    elif item.get("total") is not None:
        return quantize_money(to_decimal(item.get("total"))), qty

    if chosen_unit_price is not None:
        unit_dec = to_decimal(chosen_unit_price)
        return quantize_money(unit_dec * Decimal(qty)), qty

    return Decimal("0.00"), qty


def calculate_sales_pareto(
    invoices: list[dict[str, Any]],
    *,
    window: str = "7d",
    is_complete: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    """Compute Pareto ranking and revenue share for sold items.

    Returns deterministic data structure with coverage metadata.
    """
    valid_invoices = [
        inv
        for inv in invoices
        if isinstance(inv, dict) and _is_valid_released_invoice(inv)
    ]
    scanned_count = len(invoices)

    product_map: dict[str, dict[str, Any]] = {}

    for inv in valid_invoices:
        items = inv.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            line_rev, qty = _extract_item_revenue(item)
            if qty <= 0:
                continue

            product_obj = item.get("product")
            p_id = ""
            p_name = ""
            sku = item.get("sku") or ""

            if isinstance(product_obj, dict):
                p_id = str(product_obj.get("id") or product_obj.get("_id") or "")
                p_name = str(product_obj.get("name") or "")
            elif isinstance(product_obj, str) and product_obj.strip():
                p_id = product_obj.strip()

            if not p_name:
                p_name = str(item.get("productName") or "")
            if not p_id:
                p_id = str(item.get("productId") or "")
            if not p_id:
                p_id = p_name or "unknown"
            if not p_name:
                p_name = p_id

            if p_id not in product_map:
                product_map[p_id] = {
                    "productId": p_id,
                    "productName": p_name,
                    "sku": str(sku or ""),
                    "unitsSold": 0,
                    "revenue": Decimal("0.00"),
                    "orderCount": 0,
                }

            product_map[p_id]["unitsSold"] += qty
            product_map[p_id]["revenue"] += line_rev
            product_map[p_id]["orderCount"] += 1

    total_revenue = sum((p["revenue"] for p in product_map.values()), Decimal("0.00"))
    total_units_sold = sum((p["unitsSold"] for p in product_map.values()), 0)
    total_products_sold = len(product_map)

    if total_revenue <= Decimal("0.00") or total_products_sold == 0:
        return {
            "totalRevenue": "0.00",
            "totalUnitsSold": total_units_sold,
            "totalProductsSold": total_products_sold,
            "paretoThresholdPct": 80.0,
            "paretoTopCount": 0,
            "paretoRatio": "0 of 0 products generate 80% of revenue",
            "topProducts": [],
            "paretoProducts": [],
            "coverage": CoverageMetadata(
                scanned_bills=scanned_count,
                window=window,
                is_complete=is_complete,
            ).to_dict(),
        }

    sorted_products = sorted(
        product_map.values(),
        key=lambda x: (x["revenue"], x["unitsSold"]),
        reverse=True,
    )

    ranked_products: list[dict[str, Any]] = []
    pareto_products: list[dict[str, Any]] = []
    cumulative_rev = Decimal("0.00")
    pareto_threshold_reached = False

    for rank, p in enumerate(sorted_products, start=1):
        rev = p["revenue"]
        cumulative_rev += rev
        share_pct = quantize_pct((rev / total_revenue) * Decimal("100.0"))
        cum_pct = quantize_pct((cumulative_rev / total_revenue) * Decimal("100.0"))

        item_entry = {
            "rank": rank,
            "productId": p["productId"],
            "productName": p["productName"],
            "sku": p["sku"],
            "unitsSold": p["unitsSold"],
            "revenue": str(quantize_money(rev)),
            "revenueSharePct": float(share_pct),
            "cumulativeSharePct": float(cum_pct),
            "orderCount": p["orderCount"],
        }
        ranked_products.append(item_entry)

        if not pareto_threshold_reached:
            pareto_products.append(item_entry)
            if cum_pct >= Decimal("80.0"):
                pareto_threshold_reached = True

    pareto_top_count = len(pareto_products)
    catalog_share_pct = quantize_pct(
        (Decimal(pareto_top_count) / Decimal(total_products_sold)) * Decimal("100.0")
    )
    ratio_str = (
        f"{pareto_top_count} of {total_products_sold} products "
        f"({float(catalog_share_pct):.1f}%) generate 80% of revenue"
    )

    capped_top = ranked_products[: max(1, limit)]

    return {
        "totalRevenue": str(quantize_money(total_revenue)),
        "totalUnitsSold": total_units_sold,
        "totalProductsSold": total_products_sold,
        "paretoThresholdPct": 80.0,
        "paretoTopCount": pareto_top_count,
        "paretoRatio": ratio_str,
        "topProducts": capped_top,
        "paretoProducts": pareto_products,
        "coverage": CoverageMetadata(
            scanned_bills=scanned_count,
            window=window,
            is_complete=is_complete,
        ).to_dict(),
    }
