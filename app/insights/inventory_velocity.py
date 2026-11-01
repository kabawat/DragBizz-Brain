"""Deterministic inventory movement and sales velocity scanning engine.

Correlates observed invoice item sales against catalog inventory levels.
Strictly distinguishes 'zero observed sales in scanned window' from absolute dead stock.
"""

from __future__ import annotations

from typing import Any

from app.insights.common import CoverageMetadata


def _extract_sales_by_product(
    invoices: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    """Extract units sold and bill occurrences keyed by product ID and name."""
    units_sold: dict[str, int] = {}
    bill_counts: dict[str, int] = {}
    product_names: dict[str, str] = {}

    for inv in invoices:
        if not isinstance(inv, dict):
            continue
        status = str(inv.get("invoiceStatus") or "").upper().strip()
        if status and status != "RELEASED":
            continue
        if inv.get("cancelledAt") or inv.get("cancellationReason"):
            continue

        items = inv.get("items")
        if not isinstance(items, list):
            continue

        seen_in_bill: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            qty = int(item.get("quantity") or 0)
            if qty <= 0:
                continue

            product_obj = item.get("product")
            p_id = ""
            p_name = ""

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

            units_sold[p_id] = units_sold.get(p_id, 0) + qty
            product_names[p_id] = p_name

            if p_id not in seen_in_bill:
                seen_in_bill.add(p_id)
                bill_counts[p_id] = bill_counts.get(p_id, 0) + 1

    return units_sold, bill_counts, product_names


def calculate_inventory_velocity(
    stock_items: list[dict[str, Any]],
    invoices: list[dict[str, Any]],
    *,
    window: str = "7d",
    is_complete: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    """Calculate inventory velocity and highlight products with zero observed sales.

    Distinguishes zero sales in scanned window from store-wide lifetime dead stock.
    """
    scanned_bills = len(invoices)
    scanned_stock = len(stock_items)

    units_by_product, bills_by_product, names_by_product = _extract_sales_by_product(
        invoices
    )

    active_sellers: list[dict[str, Any]] = []
    zero_sales_items: list[dict[str, Any]] = []
    low_stock_items: list[dict[str, Any]] = []

    for item in stock_items:
        if not isinstance(item, dict):
            continue

        p_id = str(item.get("productId") or item.get("id") or item.get("_id") or "")
        name = str(item.get("name") or names_by_product.get(p_id) or "Product")
        sku = str(item.get("sku") or "")
        category = str(item.get("category") or "")
        available_qty = int(item.get("availableQuantity") or 0)
        threshold = int(item.get("lowStockThreshold") or 0)
        is_low = bool(
            item.get("isLowStock") or (available_qty <= threshold and available_qty > 0)
        )
        is_out = bool(item.get("isOutOfStock") or (available_qty <= 0))

        sold_qty = units_by_product.get(p_id, 0)
        if sold_qty == 0 and name in units_by_product:
            sold_qty = units_by_product[name]
        bills_count = bills_by_product.get(p_id, 0)
        if bills_count == 0 and name in bills_by_product:
            bills_count = bills_by_product[name]

        stock_record = {
            "productId": p_id,
            "productName": name,
            "sku": sku,
            "category": category,
            "availableQuantity": available_qty,
            "lowStockThreshold": threshold,
            "unitsSoldInWindow": sold_qty,
            "billsCountInWindow": bills_count,
            "isLowStock": is_low,
            "isOutOfStock": is_out,
        }

        if is_low or is_out:
            low_stock_items.append(stock_record)

        if sold_qty > 0:
            active_sellers.append(stock_record)
        elif available_qty > 0:
            if not is_complete:
                note = (
                    f"0 sales observed in partial/capped scan ({scanned_bills} bills "
                    f"over {window}); not confirmed dead stock"
                )
            else:
                note = (
                    f"0 sales observed in {scanned_bills} bills over {window}; "
                    "not confirmed dead stock"
                )
            zero_sales_items.append(
                {
                    **stock_record,
                    "zeroSalesInScannedWindow": True,
                    "observationNote": note,
                }
            )

    sorted_sellers = sorted(
        active_sellers,
        key=lambda x: (x["unitsSoldInWindow"], x["billsCountInWindow"]),
        reverse=True,
    )

    sorted_zero_sales = sorted(
        zero_sales_items,
        key=lambda x: x["availableQuantity"],
        reverse=True,
    )

    capped_sellers = sorted_sellers[: max(1, limit)]
    capped_zero_sales = sorted_zero_sales[: max(1, limit)]
    capped_low_stock = low_stock_items[: max(1, limit)]

    return {
        "totalStockItemsScanned": scanned_stock,
        "itemsWithSalesInWindow": len(active_sellers),
        "zeroObservedSalesCount": len(zero_sales_items),
        "lowStockCount": len(low_stock_items),
        "fastMovingItems": capped_sellers,
        "zeroObservedSalesItems": capped_zero_sales,
        "lowStockItems": capped_low_stock,
        "coverage": CoverageMetadata(
            scanned_bills=scanned_bills,
            scanned_stock_items=scanned_stock,
            window=window,
            is_complete=is_complete,
        ).to_dict(),
    }
