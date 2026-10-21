"""Post-execution projection of tool result data for model/guard/client.

Runs only after Phase 1/2 governance and Retailer execution. Copies
allowlisted fields. Never recomputes totals or rewrites store identity.
"""

from __future__ import annotations

import re
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
_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SENSITIVE_ERROR_TEXT = re.compile(
    r"(?:traceback|stack trace|\bFile \"[^\"]+\", line \d+|"
    r"mongodb(?:\+srv)?://|postgres(?:ql)?://|Bearer\s+\S+)",
    re.IGNORECASE,
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


def _error_passthrough(_data: dict[str, Any]) -> dict[str, Any]:
    """Preserve safe error summaries while stripping internal diagnostics."""
    code = _data.get("code")
    if not isinstance(code, str) or not _SAFE_ERROR_CODE.fullmatch(code):
        code = "TOOL_FAILED"
    message = _data.get("message")
    if (
        not isinstance(message, str)
        or len(message) > 300
        or _SENSITIVE_ERROR_TEXT.search(message)
    ):
        message = "The requested store information or action could not be completed."
    return {
        "code": code,
        "message": message,
    }


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
    for key in ("totalDue", "remainingDue"):
        if _is_number(data.get(key)):
            out[key] = data[key]
    return out


def project_add_stock(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        out: dict[str, Any] = {"status": "pending_confirmation"}
        if isinstance(data.get("confirmationId"), str):
            out["confirmationId"] = data["confirmationId"]
        if isinstance(data.get("draftId"), str):
            out["draftId"] = data["draftId"]
        summary = data.get("summary")
        if isinstance(summary, dict):
            out["summary"] = summary
        return out
    out = {}
    if isinstance(data.get("count"), int):
        out["count"] = data["count"]
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items[:_MAX_LIST]:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            if isinstance(item.get("productId"), str):
                row["productId"] = item["productId"]
            for key in (
                "productName",
                "sourceName",
                "quantity",
                "currentStock",
                "finalStock",
                "batchNo",
            ):
                if key in item:
                    row[key] = item[key]
            if row:
                items.append(row)
    if items:
        out["items"] = items
    return out


def project_create_expense(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        out: dict[str, Any] = {"status": "pending_confirmation"}
        if isinstance(data.get("confirmationId"), str):
            out["confirmationId"] = data["confirmationId"]
        if isinstance(data.get("draftId"), str):
            out["draftId"] = data["draftId"]
        summary = data.get("summary")
        if isinstance(summary, dict):
            out["summary"] = summary
        return out
    return _pick(
        data,
        (
            "id",
            "title",
            "amount",
            "category",
            "date",
            "paymentMode",
            "openPath",
        ),
    )


def project_create_purchase_order(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        out: dict[str, Any] = {"status": "pending_confirmation"}
        if isinstance(data.get("confirmationId"), str):
            out["confirmationId"] = data["confirmationId"]
        if isinstance(data.get("draftId"), str):
            out["draftId"] = data["draftId"]
        summary = data.get("summary")
        if isinstance(summary, dict):
            out["summary"] = summary
        return out
    return _pick(
        data,
        (
            "id",
            "poNumber",
            "supplierId",
            "supplierName",
            "itemCount",
            "totalQuantity",
            "status",
            "openPath",
        ),
    )


def project_update_expense(data: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        data,
        (
            "id",
            "title",
            "amount",
            "category",
            "date",
            "paymentMode",
            "status",
            "openPath",
        ),
    )


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


def project_product_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    totals = data.get("totals")
    if isinstance(totals, dict):
        picked = _pick(totals, ("totalProducts", "activeProducts", "inactiveProducts"))
        if picked:
            out["totals"] = picked
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
    note = item.get("note")
    if isinstance(note, str) and note.strip():
        row["note"] = note.strip()[:200]
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


def project_customer_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("totalCustomers", "todayCustomers"):
        if key in data:
            out[key] = data[key]
    new_customers = data.get("newCustomers")
    if isinstance(new_customers, dict):
        picked = _pick(
            new_customers,
            (
                "last1Day",
                "last7Days",
                "last15Days",
                "last30Days",
                "last3Months",
                "last6Months",
                "last12Months",
            ),
        )
        if picked:
            out["newCustomers"] = picked
    period = data.get("period")
    if isinstance(period, dict):
        period_out: dict[str, Any] = {}
        if isinstance(period.get("days"), int):
            period_out["days"] = period["days"]
        for key in ("startDate", "endDate"):
            if isinstance(period.get(key), str):
                period_out[key] = period[key]
        summary = period.get("summary")
        if isinstance(summary, dict):
            picked = _pick(
                summary,
                (
                    "totalCustomers",
                    "todayCustomers",
                    "periodCustomers",
                    "growthRate",
                    "avgDailyCustomers",
                    "maxDailyCustomers",
                    "minDailyCustomers",
                ),
            )
            if picked:
                period_out["summary"] = picked
        period_new = period.get("newCustomers")
        if isinstance(period_new, dict):
            picked = _pick(
                period_new,
                (
                    "last1Day",
                    "last7Days",
                    "last15Days",
                    "last30Days",
                    "last3Months",
                    "last6Months",
                    "last12Months",
                ),
            )
            if picked:
                period_out["newCustomers"] = picked
        if period_out:
            out["period"] = period_out
    return out


def project_customer_ledger(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data.get("customerId"), str):
        out["customerId"] = data["customerId"]
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items[:_MAX_LEDGER_ENTRIES]:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            entity_id = _entity_id(item)
            if entity_id is not None:
                row["id"] = entity_id
            for key in (
                "transactionNumber",
                "type",
                "source",
                "paymentMode",
                "reference",
                "notes",
                "transactionDate",
            ):
                if isinstance(item.get(key), str):
                    row[key] = item[key]
            for key in ("amount", "runningBalance"):
                if _is_number(item.get(key)):
                    row[key] = item[key]
            if row:
                items.append(row)
    out["items"] = items
    return out


def project_customer_accounts(data: dict[str, Any]) -> dict[str, Any]:
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
            customer = item.get("customer")
            if isinstance(customer, dict):
                cust: dict[str, Any] = {}
                cust_id = _entity_id(customer)
                if cust_id is not None:
                    cust["id"] = cust_id
                for key in ("name", "phone", "email"):
                    if isinstance(customer.get(key), str):
                        cust[key] = customer[key]
                if cust:
                    row["customer"] = cust
            elif isinstance(item.get("customer"), str):
                row["customerId"] = item["customer"]
            for key in (
                "totalDue",
                "totalPaid",
                "totalAmount",
                "accountStatus",
            ):
                if key in item:
                    row[key] = item[key]
            if row:
                items.append(row)
    return {"items": items}


def project_payment_detail(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    entity_id = _entity_id(data) or _entity_id(data.get("payment"))
    if entity_id is not None:
        out["id"] = entity_id
    source = data.get("payment") if isinstance(data.get("payment"), dict) else data
    if isinstance(source, dict):
        for key in (
            "paymentType",
            "paymentStatus",
            "notes",
            "paymentDate",
        ):
            if isinstance(source.get(key), str):
                out[key] = source[key]
        if _is_number(source.get("totalAmount")):
            out["totalAmount"] = source["totalAmount"]
        customer = source.get("customer")
        if isinstance(customer, str):
            out["customerId"] = customer
        elif isinstance(customer, dict):
            cust_id = _entity_id(customer)
            if cust_id is not None:
                out["customerId"] = cust_id
    return out


def project_payment_reminders(data: dict[str, Any]) -> dict[str, Any]:
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
            for key in ("channel", "status", "notes"):
                if isinstance(item.get(key), str):
                    row[key] = item[key]
            customer = item.get("customer")
            if isinstance(customer, str):
                row["customerId"] = customer
            elif isinstance(customer, dict):
                cust_id = _entity_id(customer)
                if cust_id is not None:
                    row["customerId"] = cust_id
            if row:
                items.append(row)
    return {"items": items}


def project_merge_customers(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        return _project_pending(data)
    out: dict[str, Any] = {}
    for key in ("primaryId", "duplicateId", "openPath"):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    customer = data.get("customer")
    if isinstance(customer, dict):
        projected = project_customer_write({"customer": customer})
        if projected:
            out["customer"] = projected.get("customer") or {
                k: projected[k]
                for k in ("id", "name", "phone", "email")
                if k in projected
            }
    return out


def project_opening_balance(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        return _project_pending(data)
    out: dict[str, Any] = {}
    if isinstance(data.get("customerId"), str):
        out["customerId"] = data["customerId"]
    if isinstance(data.get("openPath"), str):
        out["openPath"] = data["openPath"]
    for key in ("totalDue", "totalPaid", "totalAmount"):
        if _is_number(data.get(key)):
            out[key] = data[key]
    entity_id = _entity_id(data) or _entity_id(data.get("account"))
    if entity_id is not None:
        out["id"] = entity_id
    return out


def project_customer_payment_write(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        return _project_pending(data)
    out = project_payment_detail(data)
    if isinstance(data.get("customerId"), str):
        out["customerId"] = data["customerId"]
    if _is_number(data.get("amount")):
        out["amount"] = data["amount"]
    if isinstance(data.get("openPath"), str):
        out["openPath"] = data["openPath"]
    return out


def project_collect_link(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        return _project_pending(data)
    out: dict[str, Any] = {}
    entity_id = _entity_id(data)
    if entity_id is not None:
        out["id"] = entity_id
    for key in (
        "customerId",
        "openPath",
        "status",
        "gatewayShortUrl",
        "publicToken",
        "collectType",
    ):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    if _is_number(data.get("amount")):
        out["amount"] = data["amount"]
    return out


def project_payment_reminder_write(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "pending_confirmation":
        return _project_pending(data)
    out: dict[str, Any] = {}
    entity_id = _entity_id(data) or _entity_id(data.get("reminder"))
    if entity_id is not None:
        out["id"] = entity_id
    for key in ("customerId", "openPath", "channel", "status"):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    return out


def _project_pending(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "pending_confirmation"}
    if isinstance(data.get("confirmationId"), str):
        out["confirmationId"] = data["confirmationId"]
    if isinstance(data.get("draftId"), str):
        out["draftId"] = data["draftId"]
    summary = data.get("summary")
    if isinstance(summary, dict):
        out["summary"] = summary
    return out


def project_invoice_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    counts = data.get("counts")
    if isinstance(counts, dict):
        picked = _pick(
            counts,
            (
                "totalInvoices",
                "releasedInvoices",
                "draftInvoices",
                "cancelledInvoices",
            ),
        )
        if picked:
            out["counts"] = picked
    amounts = data.get("amounts")
    if isinstance(amounts, dict):
        picked = _pick(amounts, ("totalAmount", "averageOrderValue"))
        if picked:
            out["amounts"] = picked
    today = data.get("today")
    if isinstance(today, dict):
        picked = _pick(
            today,
            ("totalInvoices", "releasedInvoices", "revenue", "profit", "sales"),
        )
        if picked:
            out["today"] = picked
    summary = data.get("summary")
    if isinstance(summary, dict):
        picked = _pick(
            summary,
            ("totalRevenue", "totalProfit", "totalSales", "avgOrderValue"),
        )
        if picked:
            out["summary"] = picked
    period = data.get("period")
    if isinstance(period, dict):
        period_out: dict[str, Any] = {}
        if isinstance(period.get("days"), int):
            period_out["days"] = period["days"]
        for key in ("startDate", "endDate"):
            if isinstance(period.get(key), str):
                period_out[key] = period[key]
        summary = period.get("summary")
        if isinstance(summary, dict):
            picked = _pick(
                summary,
                ("totalRevenue", "totalProfit", "totalSales", "avgOrderValue"),
            )
            if picked:
                period_out["summary"] = picked
        period_today = period.get("today")
        if isinstance(period_today, dict):
            picked = _pick(period_today, ("revenue", "profit", "sales"))
            if picked:
                period_out["today"] = picked
        if period_out:
            out["period"] = period_out
    return out


def project_list_stores(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("stores")
    stores: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items[:_MAX_LIST]:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            entity_id = _entity_id(item)
            if entity_id is not None:
                row["id"] = entity_id
            elif isinstance(item.get("id"), str):
                row["id"] = item["id"]
            if isinstance(item.get("name"), str):
                row["name"] = item["name"]
            if isinstance(item.get("category"), str):
                row["category"] = item["category"]
            subs = item.get("subCategories")
            if isinstance(subs, list):
                clean_subs = [
                    sub for sub in subs if isinstance(sub, str) and sub.strip()
                ]
                if clean_subs:
                    row["subCategories"] = clean_subs[:12]
            tags = item.get("tags")
            if isinstance(tags, list):
                clean_tags = [
                    tag for tag in tags if isinstance(tag, str) and tag.strip()
                ]
                if clean_tags:
                    row["tags"] = clean_tags[:12]
            if item.get("active") is True:
                row["active"] = True
            if row:
                stores.append(row)
    out: dict[str, Any] = {
        "count": data["count"] if isinstance(data.get("count"), int) else len(stores),
        "stores": stores,
    }
    if isinstance(data.get("activeStoreId"), str):
        out["activeStoreId"] = data["activeStoreId"]
    if isinstance(data.get("activeStoreName"), str):
        out["activeStoreName"] = data["activeStoreName"]
    if isinstance(data.get("activeStoreCategory"), str):
        out["activeStoreCategory"] = data["activeStoreCategory"]
    active_subs = data.get("activeStoreSubCategories")
    if isinstance(active_subs, list):
        clean = [sub for sub in active_subs if isinstance(sub, str) and sub.strip()]
        if clean:
            out["activeStoreSubCategories"] = clean[:12]
    return out


_DOSSIER_BILL_CAP = 10
_DOSSIER_LINE_CAP = 5
_DOSSIER_STATUSES = frozenset({"ok", "empty", "ambiguous", "unavailable", "no_match"})


def project_customer_dossier(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict):
                items.append(_project_dossier_customer(item))
    out: dict[str, Any] = {"items": items}
    query = data.get("query")
    if isinstance(query, str) and query.strip():
        out["query"] = query.strip()[:200]
    match_by = data.get("matchBy")
    if match_by in {"name", "phone", "email", "none"}:
        out["matchBy"] = match_by
    match_count = data.get("matchCount")
    if isinstance(match_count, int) and not isinstance(match_count, bool):
        out["matchCount"] = match_count
    status = data.get("billsStatus")
    if isinstance(status, str) and status in _DOSSIER_STATUSES:
        out["billsStatus"] = status
    scanned = data.get("billsScanned")
    if isinstance(scanned, int) and not isinstance(scanned, bool):
        out["billsScanned"] = scanned
    if isinstance(data.get("billsError"), str):
        out["billsError"] = data["billsError"]
    bills = _project_dossier_bills(data.get("bills"))
    if bills:
        out["bills"] = bills
    return out


def _project_dossier_customer(item: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    entity_id = _entity_id(item)
    if entity_id is not None:
        row["id"] = entity_id
    elif isinstance(item.get("id"), str):
        row["id"] = item["id"]
    for key in ("name", "phone", "email", "isActive"):
        if key in item:
            row[key] = item[key]
    memo = _truncate_notes(item.get("memo"))
    if memo is None:
        memo = _truncate_notes(item.get("note"))
    if memo is not None:
        row["memo"] = memo
    account = item.get("account")
    if isinstance(account, dict):
        picked = _pick(account, ("totalDue", "totalPaid"))
        if picked:
            row["account"] = picked
    return row


def _project_dossier_bills(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    bills: list[dict[str, Any]] = []
    for bill in raw[:_DOSSIER_BILL_CAP]:
        if not isinstance(bill, dict):
            continue
        row: dict[str, Any] = {}
        if isinstance(bill.get("id"), str) and bill["id"]:
            row["id"] = bill["id"]
        for key in (
            "invoiceNumber",
            "date",
            "paymentMode",
            "paymentStatus",
            "invoiceStatus",
        ):
            if key in bill:
                row[key] = bill[key]
        if _is_number(bill.get("totalAmount")):
            row["totalAmount"] = bill["totalAmount"]
        lines = bill.get("items")
        if isinstance(lines, list):
            clean: list[dict[str, Any]] = []
            for line in lines:
                if len(clean) >= _DOSSIER_LINE_CAP:
                    break
                if not isinstance(line, dict):
                    continue
                name = line.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                projected: dict[str, Any] = {"name": name.strip()}
                if _is_number(line.get("qty")):
                    projected["qty"] = line["qty"]
                clean.append(projected)
            if clean:
                row["items"] = clean
        if row:
            bills.append(row)
    return bills


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
    match_by = data.get("matchBy")
    if match_by in {"name", "phone", "email", "none"}:
        out["matchBy"] = match_by
    return out


def project_top_customers(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items[:20]:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            if isinstance(item.get("id"), str) and item["id"]:
                row["id"] = item["id"]
            if isinstance(item.get("name"), str):
                row["name"] = item["name"]
            if isinstance(item.get("phone"), str) and item["phone"]:
                row["phone"] = item["phone"]
            if _is_number(item.get("total")):
                row["total"] = item["total"]
            bills = item.get("bills")
            if isinstance(bills, int) and not isinstance(bills, bool):
                row["bills"] = bills
            if row:
                items.append(row)
    out: dict[str, Any] = {"items": items}
    scanned = data.get("billsScanned")
    if isinstance(scanned, int) and not isinstance(scanned, bool):
        out["billsScanned"] = scanned
    if isinstance(data.get("capped"), bool):
        out["capped"] = data["capped"]
    return out


def project_stock_items(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return {"count": 0, "items": []}
    items: list[dict[str, Any]] = []
    for item in raw_items[:30]:
        if not isinstance(item, dict):
            continue
        picked = _pick(
            item,
            (
                "id",
                "name",
                "sku",
                "stock",
                "status",
                "sellingPrice",
                "purchasePrice",
            ),
        )
        if picked:
            items.append(picked)
    out: dict[str, Any] = {"count": len(items), "items": items}
    if isinstance(data.get("coverage"), str):
        out["coverage"] = data["coverage"]
    return out


def project_list_invoices(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("invoices")
    if not isinstance(raw, list):
        return {"count": 0, "invoices": []}
    invoices: list[dict[str, Any]] = []
    for inv in raw[:30]:
        if not isinstance(inv, dict):
            continue
        entry: dict[str, Any] = {}
        for key in (
            "id",
            "invoiceNumber",
            "invoiceDate",
            "totalAmount",
            "paymentStatus",
            "invoiceStatus",
            "itemCount",
        ):
            if key in inv:
                entry[key] = inv[key]
        cust = inv.get("customer")
        if isinstance(cust, dict):
            entry["customer"] = _pick(cust, ("id", "name", "phone"))
        invoices.append(entry)
    out: dict[str, Any] = {"count": len(invoices), "invoices": invoices}
    if isinstance(data.get("status"), str):
        out["status"] = data["status"]
    return out


def project_expense_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    totals = data.get("totals")
    if isinstance(totals, dict):
        out["totals"] = _pick(
            totals,
            ("totalExpenses", "totalAmount", "paidAmount", "pendingAmount"),
        )
    cats = data.get("byCategory")
    if isinstance(cats, list):
        clean_cats = []
        for c in cats[:10]:
            if isinstance(c, dict):
                clean_cats.append(
                    _pick(c, ("category", "amount", "count", "percentage"))
                )
        if clean_cats:
            out["byCategory"] = clean_cats
    return out


def project_list_expenses(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("expenses")
    if not isinstance(raw, list):
        return {"count": 0, "expenses": []}
    expenses: list[dict[str, Any]] = []
    for exp in raw[:20]:
        if not isinstance(exp, dict):
            continue
        picked = _pick(
            exp,
            (
                "id",
                "expenseNumber",
                "title",
                "category",
                "amount",
                "paymentMode",
                "date",
                "status",
            ),
        )
        if picked:
            expenses.append(picked)
    return {"count": len(expenses), "expenses": expenses}


def project_cashbook_summary(data: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        data,
        (
            "openingBalance",
            "closingBalance",
            "totalCashIn",
            "totalCashOut",
            "netBalance",
            "cashSales",
            "dayStatus",
        ),
    )


def project_search_supplier(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("suppliers")
    if not isinstance(raw, list):
        return {"count": 0, "suppliers": []}
    suppliers: list[dict[str, Any]] = []
    for s in raw[:20]:
        if not isinstance(s, dict):
            continue
        picked = _pick(
            s,
            (
                "id",
                "name",
                "phone",
                "email",
                "companyName",
                "gstNumber",
                "totalDue",
            ),
        )
        if picked:
            suppliers.append(picked)
    return {"count": len(suppliers), "suppliers": suppliers}


def project_supplier_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    counts = data.get("counts")
    if isinstance(counts, dict):
        out["counts"] = _pick(
            counts,
            (
                "totalSuppliers",
                "activeSuppliers",
                "inactiveSuppliers",
                "withDues",
            ),
        )
    amounts = data.get("amounts")
    if isinstance(amounts, dict):
        out["amounts"] = _pick(amounts, ("totalPayable", "totalPaid", "totalDue"))
    bills = data.get("bills")
    if isinstance(bills, dict):
        out["bills"] = _pick(bills, ("totalBills", "pendingBills", "overdueBills"))
    return out


def project_list_purchase_orders(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("purchaseOrders")
    if not isinstance(raw, list):
        return {"count": 0, "purchaseOrders": []}
    orders: list[dict[str, Any]] = []
    for po in raw[:20]:
        if not isinstance(po, dict):
            continue
        entry = _pick(
            po,
            (
                "id",
                "poNumber",
                "poDate",
                "status",
                "approvalStatus",
                "totalAmount",
                "itemCount",
            ),
        )
        supp = po.get("supplier")
        if isinstance(supp, dict):
            entry["supplier"] = _pick(supp, ("id", "name"))
        orders.append(entry)
    return {"count": len(orders), "purchaseOrders": orders}


def project_bill_summary(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    counts = data.get("counts")
    if isinstance(counts, dict):
        out["counts"] = _pick(
            counts,
            ("totalBills", "paidBills", "pendingBills", "overdueBills"),
        )
    amounts = data.get("amounts")
    if isinstance(amounts, dict):
        out["amounts"] = _pick(
            amounts,
            ("totalPayable", "totalPaid", "totalDue", "totalGst"),
        )
    return out


def project_gst_summary(data: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        data,
        (
            "period",
            "totalTaxableAmount",
            "totalTax",
            "cgst",
            "sgst",
            "igst",
            "invoiceCount",
            "healthScore",
        ),
    )


def project_list_sales_orders(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("salesOrders")
    if not isinstance(raw, list):
        return {"count": 0, "salesOrders": []}
    orders: list[dict[str, Any]] = []
    for so in raw[:20]:
        if not isinstance(so, dict):
            continue
        entry = _pick(
            so,
            (
                "id",
                "orderNumber",
                "orderDate",
                "status",
                "paymentStatus",
                "totalAmount",
            ),
        )
        cust = so.get("customer")
        if isinstance(cust, dict):
            entry["customer"] = _pick(cust, ("id", "name", "phone"))
        orders.append(entry)
    return {"count": len(orders), "salesOrders": orders}


def project_list_staff(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("staff")
    if not isinstance(raw, list):
        return {"count": 0, "staff": []}
    staff_list: list[dict[str, Any]] = []
    for m in raw[:20]:
        if not isinstance(m, dict):
            continue
        picked = _pick(m, ("id", "name", "phone", "role", "status"))
        if picked:
            staff_list.append(picked)
    return {"count": len(staff_list), "staff": staff_list}


def project_customer_detailed_analytics(
    data: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("summary", "today", "period", "growth", "newCustomers"):
        val = data.get(key)
        if isinstance(val, dict):
            out[key] = val
    return out or dict(data)


def project_invoice_detailed_analytics(
    data: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "summary",
        "today",
        "period",
        "growth",
        "previous",
        "statusBreakdown",
        "paymentBreakdown",
        "trends",
        "hourly",
    ):
        val = data.get(key)
        if isinstance(val, (dict, list)):
            out[key] = val
    return out or dict(data)


def project_sales_pareto(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "totalRevenue",
        "totalUnitsSold",
        "totalProductsSold",
        "paretoThresholdPct",
        "paretoTopCount",
        "paretoRatio",
    ):
        if key in data:
            out[key] = data[key]

    for list_key in ("topProducts", "paretoProducts"):
        raw_list = data.get(list_key)
        if isinstance(raw_list, list):
            items = []
            for item in raw_list[:_MAX_LIST]:
                if isinstance(item, dict):
                    items.append(
                        {
                            "rank": item.get("rank"),
                            "productId": str(item.get("productId") or ""),
                            "productName": item.get("productName"),
                            "sku": item.get("sku"),
                            "unitsSold": item.get("unitsSold"),
                            "revenue": item.get("revenue"),
                            "revenueSharePct": item.get("revenueSharePct"),
                            "cumulativeSharePct": item.get("cumulativeSharePct"),
                        }
                    )
            out[list_key] = items

    cov = data.get("coverage")
    if isinstance(cov, dict):
        out["coverage"] = dict(cov)
    return out or dict(data)


def project_payment_mix(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "totalInvoiced",
        "totalAmount",
        "totalCollected",
        "totalUncollectedCredit",
        "invoiceCount",
        "primaryMode",
    ):
        if key in data:
            out[key] = data[key]

    raw_bd = data.get("breakdown")
    if isinstance(raw_bd, dict):
        out["breakdown"] = dict(raw_bd)

    cov = data.get("coverage")
    if isinstance(cov, dict):
        out["coverage"] = dict(cov)
    return out or dict(data)


def project_inventory_velocity(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "totalStockItemsScanned",
        "itemsWithSalesInWindow",
        "zeroObservedSalesCount",
        "lowStockCount",
    ):
        if key in data:
            out[key] = data[key]

    for list_key in ("fastMovingItems", "zeroObservedSalesItems", "lowStockItems"):
        raw_list = data.get(list_key)
        if isinstance(raw_list, list):
            items = []
            for item in raw_list[:_MAX_LIST]:
                if isinstance(item, dict):
                    items.append(
                        {
                            "productId": str(item.get("productId") or ""),
                            "productName": item.get("productName"),
                            "sku": item.get("sku"),
                            "category": item.get("category"),
                            "availableQuantity": item.get("availableQuantity"),
                            "lowStockThreshold": item.get("lowStockThreshold"),
                            "unitsSoldInWindow": item.get("unitsSoldInWindow"),
                            "billsCountInWindow": item.get("billsCountInWindow"),
                            "isLowStock": item.get("isLowStock"),
                            "isOutOfStock": item.get("isOutOfStock"),
                            "zeroSalesInScannedWindow": item.get(
                                "zeroSalesInScannedWindow"
                            ),
                            "observationNote": item.get("observationNote"),
                        }
                    )
            out[list_key] = items

    cov = data.get("coverage")
    if isinstance(cov, dict):
        out["coverage"] = dict(cov)
    return out or dict(data)


def project_store_brief(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "date",
        "todaySales",
        "inventoryHealth",
        "customerReceivables",
        "expenses",
        "netCashflowIndication",
        "netCashflowStatus",
    ):
        if key in data:
            out[key] = data[key]

    cov = data.get("coverage")
    if isinstance(cov, dict):
        out["coverage"] = dict(cov)
    return out or dict(data)


TOOL_PROJECTORS: dict[str, _Projector] = {
    "payment_history": project_payment_history,
    "create_invoice_draft": project_invoice_result,
    "update_invoice_draft": project_invoice_result,
    "release_invoice": project_invoice_result,
    "create_customer": project_customer_write,
    "update_customer": project_customer_write,
    "ledger_credit": project_ledger_write,
    "ledger_debit": project_ledger_write,
    "add_stock": project_add_stock,
    "merge_customers": project_merge_customers,
    "set_opening_balance": project_opening_balance,
    "record_customer_payment": project_customer_payment_write,
    "update_customer_payment": project_customer_payment_write,
    "create_collect_link": project_collect_link,
    "send_payment_reminder": project_payment_reminder_write,
    "today_sale": project_today_sale,
    "stock_summary": project_stock_summary,
    "product_summary": project_product_summary,
    "search_product": project_search_product,
    "search_customer": project_search_customer,
    "customer_dossier": project_customer_dossier,
    "top_customers": project_top_customers,
    "list_stores": project_list_stores,
    "customer_summary": project_customer_summary,
    "get_customer_ledger": project_customer_ledger,
    "list_customer_accounts": project_customer_accounts,
    "get_customer_payment": project_payment_detail,
    "list_payment_reminders": project_payment_reminders,
    "invoice_summary": project_invoice_summary,
    "stock_items": project_stock_items,
    "list_invoices": project_list_invoices,
    "expense_summary": project_expense_summary,
    "list_expenses": project_list_expenses,
    "cashbook_summary": project_cashbook_summary,
    "search_supplier": project_search_supplier,
    "supplier_summary": project_supplier_summary,
    "list_purchase_orders": project_list_purchase_orders,
    "bill_summary": project_bill_summary,
    "gst_summary": project_gst_summary,
    "list_sales_orders": project_list_sales_orders,
    "list_staff": project_list_staff,
    "customer_detailed_analytics": project_customer_detailed_analytics,
    "invoice_detailed_analytics": project_invoice_detailed_analytics,
    "create_expense": project_create_expense,
    "update_expense": project_update_expense,
    "create_purchase_order": project_create_purchase_order,
    "sales_pareto": project_sales_pareto,
    "payment_mix": project_payment_mix,
    "inventory_velocity": project_inventory_velocity,
    "store_brief": project_store_brief,
}
