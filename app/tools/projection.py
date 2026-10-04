"""Post-execution projection of tool result data for model/guard/client.

Runs only after Phase 1/2 governance and Retailer execution. Copies
allowlisted fields. Never recomputes totals or rewrites store identity.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.schemas.tool import ToolResult

_Projector = Callable[[dict[str, Any]], dict[str, Any]]

_MAX_LIST = 20
_MAX_LEDGER_ENTRIES = 40
_MAX_NOTES = 80
_ADDRESS_KEYS = ("line1", "line2", "city", "state", "pincode", "country")
_TOTAL_KEYS = ("totalAmount", "grandTotal", "total", "payableAmount")
_STOCK_TOTAL_KEYS = (
    "totalSkus",
    "totalQuantity",
    "availableQuantity",
    "reservedQuantity",
    "soldQuantity",
    "lowStockItems",
    "outOfStockItems",
)
_STOCK_VALUE_KEYS = ("averageCost", "totalStockValue")
_PRODUCT_KEYS = (
    "id",
    "name",
    "sku",
    "sellingPrice",
    "stock",
    "taxRate",
    "unit",
    "status",
)


def project_tool_result(result: ToolResult) -> ToolResult:
    """Return a ToolResult whose data is safe for model, guard, and client."""
    data = result.data
    if not isinstance(data, dict):
        return ToolResult(tool=result.tool, success=result.success, data={})

    if not result.success and ("code" in data or "message" in data):
        return ToolResult(
            tool=result.tool,
            success=False,
            data=_error_passthrough(data),
        )
    if data.get("status") == "pending_confirmation":
        return ToolResult(tool=result.tool, success=result.success, data=dict(data))

    projector = TOOL_PROJECTORS.get(result.tool)
    if projector is None:
        return ToolResult(tool=result.tool, success=result.success, data={})
    return ToolResult(
        tool=result.tool,
        success=result.success,
        data=projector(data),
    )


def project_tool_results(results: list[ToolResult]) -> list[ToolResult]:
    return [project_tool_result(result) for result in results]


def _error_passthrough(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data.get("code"), str):
        out["code"] = data["code"]
    if isinstance(data.get("message"), str):
        out["message"] = data["message"]
    return out or {"code": "TOOL_FAILED", "message": "Tool failed"}


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: data[key] for key in keys if key in data}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _entity_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("id", "_id"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _customer_ref(value: Any) -> dict[str, Any] | str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    entity_id = _entity_id(value)
    if entity_id is not None:
        out["id"] = entity_id
    if isinstance(value.get("name"), str):
        out["name"] = value["name"]
    return out or None


def _scalar_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, (bool, int, float, str)):
            out[key] = item
    return out


def _address(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _pick(value, _ADDRESS_KEYS)


def _truncate_notes(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) <= _MAX_NOTES:
        return value
    return value[: _MAX_NOTES - 3] + "..."


def _item_price(item: dict[str, Any]) -> float | int | None:
    price = item.get("price")
    if _is_number(price):
        return price
    product = item.get("product")
    if isinstance(product, dict):
        selling = product.get("sellingPrice")
        if _is_number(selling):
            return selling
    return None


def _project_invoice_body(invoice: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    entity_id = _entity_id(invoice)
    if entity_id is not None:
        body["id"] = entity_id
    for key in ("invoiceNumber", "invoiceStatus"):
        if isinstance(invoice.get(key), str):
            body[key] = invoice[key]
    for key in _TOTAL_KEYS:
        value = invoice.get(key)
        if _is_number(value):
            body[key] = value
            break
    customer = _customer_ref(invoice.get("customer"))
    if customer is not None:
        body["customer"] = customer
    raw_items = invoice.get("items")
    if isinstance(raw_items, list):
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            name = item.get("name")
            if not isinstance(name, str):
                product = item.get("product")
                if isinstance(product, dict) and isinstance(product.get("name"), str):
                    name = product["name"]
            if isinstance(name, str):
                row["name"] = name
            quantity = item.get("quantity")
            if _is_number(quantity):
                row["quantity"] = quantity
            price = _item_price(item)
            if price is not None:
                row["price"] = price
            if row:
                items.append(row)
        if len(items) > _MAX_LIST:
            body["items"] = items[:_MAX_LIST]
            body["itemsTruncated"] = True
        else:
            body["items"] = items
    return body


def project_payment_history(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items[:_MAX_LIST]:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            entity_id = _entity_id(item)
            if entity_id is not None:
                row["id"] = entity_id
            for key in (
                "paymentNumber",
                "paymentDate",
                "paymentStatus",
                "paymentMethod",
            ):
                if key in item:
                    row[key] = item[key]
            amount = item.get("totalAmount")
            if _is_number(amount):
                row["totalAmount"] = amount
            customer = _customer_ref(item.get("customer"))
            if customer is not None:
                row["customer"] = customer
            items.append(row)
    out: dict[str, Any] = {"items": items}
    pagination = data.get("pagination")
    if isinstance(pagination, dict):
        page: dict[str, Any] = {}
        if isinstance(pagination.get("limit"), int):
            page["limit"] = pagination["limit"]
        if isinstance(pagination.get("hasMore"), bool):
            page["hasMore"] = pagination["hasMore"]
        if page:
            out["pagination"] = page
    return out


def project_invoice_result(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data.get("openPath"), str):
        out["openPath"] = data["openPath"]
    if data.get("alreadyReleased") is True:
        out["alreadyReleased"] = True
    nested = data.get("invoice")
    if isinstance(nested, dict):
        out["invoice"] = _project_invoice_body(nested)
    else:
        out.update(_project_invoice_body(data))
    return out


def project_customer_write(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("existing", "message", "openPath"):
        if key in data:
            out[key] = data[key]
    nested = data.get("customer")
    source = nested if isinstance(nested, dict) else data
    if isinstance(source, dict):
        entity_id = _entity_id(source)
        if entity_id is not None:
            out["id"] = entity_id
        for key in ("name", "phone", "email"):
            if key in source:
                out[key] = source[key]
        if isinstance(nested, dict):
            customer: dict[str, Any] = {}
            if entity_id is not None:
                customer["id"] = entity_id
            for key in ("name", "phone", "email"):
                if key in nested:
                    customer[key] = nested[key]
            if customer:
                out["customer"] = customer
    return out


def project_ledger_write(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    amount = data.get("amount")
    if _is_number(amount):
        out["amount"] = amount
    entity_id = _entity_id(data) or _entity_id(data.get("transaction"))
    if entity_id is not None:
        out["id"] = entity_id
    customer_id = data.get("customerId")
    if isinstance(customer_id, str) and customer_id.strip():
        out["customerId"] = customer_id.strip()
    return out


def project_today_sale(data: dict[str, Any]) -> dict[str, Any]:
    return _pick(data, ("revenue", "profit", "sales"))


def project_stock_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    totals = data.get("totals")
    if isinstance(totals, dict):
        picked = _pick(totals, _STOCK_TOTAL_KEYS)
        if picked:
            out["totals"] = picked
    values = data.get("valueSummary")
    if isinstance(values, dict):
        picked = _pick(values, _STOCK_VALUE_KEYS)
        if picked:
            out["valueSummary"] = picked
    return out


def project_search_product(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items[:_MAX_LIST]:
            if isinstance(item, dict):
                items.append(_pick(item, _PRODUCT_KEYS))
    return {"items": items}


def _project_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("openingBalance", "closingBalance", "totalEntries", "truncated"):
        if key in ledger:
            out[key] = ledger[key]
    raw_entries = ledger.get("entries")
    entries: list[dict[str, Any]] = []
    if isinstance(raw_entries, list):
        for entry in raw_entries[:_MAX_LEDGER_ENTRIES]:
            if not isinstance(entry, dict):
                continue
            row: dict[str, Any] = {}
            for key in ("date", "debit", "credit", "balance"):
                if key in entry:
                    row[key] = entry[key]
            notes = _truncate_notes(entry.get("notes"))
            if notes is not None:
                row["notes"] = notes
            entries.append(row)
    out["entries"] = entries
    return out


def _project_customer_row(item: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    entity_id = _entity_id(item)
    if entity_id is not None:
        row["id"] = entity_id
    elif isinstance(item.get("id"), str):
        row["id"] = item["id"]
    for key in ("name", "phone", "email", "isActive"):
        if key in item:
            row[key] = item[key]
    account = item.get("account")
    if isinstance(account, dict):
        picked = _pick(account, ("totalDue", "totalPaid"))
        if picked:
            row["account"] = picked
    gst = _scalar_dict(item.get("gstDetail"))
    if gst:
        row["gstDetail"] = gst
    company = item.get("companyDetails")
    if isinstance(company, dict):
        company_out: dict[str, Any] = {}
        if isinstance(company.get("name"), str):
            company_out["name"] = company["name"]
        company_gst = _scalar_dict(company.get("gstDetail"))
        if company_gst:
            company_out["gstDetail"] = company_gst
        for key, value in company.items():
            if key in {"name", "gstDetail"}:
                continue
            if isinstance(value, (str, int, float, bool)):
                company_out[key] = value
        if company_out:
            row["companyDetails"] = company_out
    addresses = item.get("addresses")
    if isinstance(addresses, dict):
        projected_addresses: dict[str, Any] = {}
        for key in ("billing", "shipping"):
            address = _address(addresses.get(key))
            if address:
                projected_addresses[key] = address
        if projected_addresses:
            row["addresses"] = projected_addresses
    ledger = item.get("ledger")
    if isinstance(ledger, dict):
        row["ledger"] = _project_ledger(ledger)
    return row


def project_search_customer(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict):
                items.append(_project_customer_row(item))
    out: dict[str, Any] = {"items": items}
    downloads = data.get("downloads")
    if isinstance(downloads, list):
        clean: list[dict[str, Any]] = []
        for item in downloads:
            if not isinstance(item, dict):
                continue
            customer_id = item.get("customerId")
            if not isinstance(customer_id, str) or not customer_id:
                continue
            row: dict[str, Any] = {"customerId": customer_id}
            if isinstance(item.get("name"), str):
                row["name"] = item["name"]
            formats = item.get("formats")
            if isinstance(formats, list):
                row["formats"] = [fmt for fmt in formats if isinstance(fmt, str)]
            clean.append(row)
        if clean:
            out["downloads"] = clean
    return out


TOOL_PROJECTORS: dict[str, _Projector] = {
    "payment_history": project_payment_history,
    "create_invoice_draft": project_invoice_result,
    "update_invoice_draft": project_invoice_result,
    "release_invoice": project_invoice_result,
    "create_customer": project_customer_write,
    "update_customer": project_customer_write,
    "ledger_credit": project_ledger_write,
    "ledger_debit": project_ledger_write,
    "today_sale": project_today_sale,
    "stock_summary": project_stock_summary,
    "search_product": project_search_product,
    "search_customer": project_search_customer,
}
