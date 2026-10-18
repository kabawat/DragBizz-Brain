from __future__ import annotations

import re
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
            store_id=context.store_id,
            query=arguments["query"],
        )
    except RetailerHttpError as exc:
        return _failure("search_product", exc)

    raw_items = response.body.get("data") or []
    # Compact projection: enough for the LLM to pick a real id and
    # quote price/stock without dumping full productsSerializer docs.
    # Contract: GET /product list nests price under pricing; GST rate
    # at gstInfo.gstRate; unit is pricing.uom.
    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        gst = item.get("gstInfo") if isinstance(item.get("gstInfo"), dict) else {}
        stock_raw = item.get("stock")
        stock_qty: Any = stock_raw
        if isinstance(stock_raw, dict):
            for key in ("availableQuantity", "totalQuantity", "quantity"):
                if isinstance(stock_raw.get(key), (int, float)) and not isinstance(
                    stock_raw.get(key), bool
                ):
                    stock_qty = stock_raw[key]
                    break
        items.append(
            {
                "id": str(item.get("id") or ""),
                "name": item.get("name"),
                "sku": item.get("sku"),
                "sellingPrice": item.get(
                    "sellingPrice", pricing.get("sellingPrice")
                ),
                "stock": stock_qty,
                "taxRate": item.get("taxRate", gst.get("gstRate")),
                "unit": item.get("unit") or item.get("uom") or pricing.get("uom"),
                "status": item.get("status"),
            }
        )
    return ToolResult(
        tool="search_product",
        success=True,
        data={"items": items},
    )


async def today_sale(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_revenue(
            access_token=context.access_token,
            store_id=context.store_id,
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
            store_id=context.store_id,
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


async def product_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_product_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("product_summary", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    data: dict[str, Any] = {
        "totals": {
            key: totals[key]
            for key in ("totalProducts", "activeProducts", "inactiveProducts")
            if key in totals
        }
    }
    return ToolResult(tool="product_summary", success=True, data=data)


async def search_customer(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        slices = _slices_for_question(context.question)
        raw_query = arguments["query"].strip()
        phone_match = re.search(r"\b[6-9]\d{9}\b", raw_query)
        effective_query = phone_match.group(0) if phone_match else raw_query
        response = await context.retailer.get_customers(
            access_token=context.access_token,
            store_id=context.store_id,
            query=effective_query,
            include_addresses="address" in slices,
            include_account="khata" in slices or "ledger" in slices,
        )
    except RetailerHttpError as exc:
        return _failure("search_customer", exc)

    raw_items = response.body.get("data") or []
    if not raw_items and effective_query != raw_query:
        clean_name = re.sub(r"\(?[6-9]\d{9}\)?", "", raw_query).strip()
        if clean_name:
            try:
                fallback_resp = await context.retailer.get_customers(
                    access_token=context.access_token,
                    store_id=context.store_id,
                    query=clean_name,
                    include_addresses="address" in slices,
                    include_account="khata" in slices or "ledger" in slices,
                )
                raw_items = fallback_resp.body.get("data") or []
            except RetailerHttpError:
                pass
    items = [
        _customer_row(item, slices=slices)
        for item in raw_items
        if isinstance(item, dict)
    ]
    data: dict[str, Any] = {"items": items}
    if "ledger" in slices and len(items) == 1 and items[0]["id"]:
        items[0]["ledger"] = await _ledger_for_customer(
            context,
            store_id=context.store_id,
            customer_id=items[0]["id"],
        )
        data["downloads"] = _download_options(items)
    return ToolResult(
        tool="search_customer",
        success=True,
        data=data,
    )


_DOSSIER_BILL_CAP = 10
_DOSSIER_LINE_CAP = 5


async def customer_dossier(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_customers(
            access_token=context.access_token,
            store_id=context.store_id,
            query=arguments["query"],
            include_account=True,
        )
    except RetailerHttpError as exc:
        return _failure("customer_dossier", exc)

    raw_items = response.body.get("data") or []
    items = [
        _dossier_customer(item) for item in raw_items if isinstance(item, dict)
    ]
    items = _narrow_dossier_customers(items, arguments["query"])
    match_count = len(items)
    data: dict[str, Any] = {
        "query": arguments["query"],
        "items": items,
        "matchCount": match_count,
        "billsScanned": 0,
    }
    if match_count == 0:
        data["billsStatus"] = "no_match"
        return ToolResult(tool="customer_dossier", success=True, data=data)
    if match_count != 1 or not items[0].get("id"):
        data["items"] = [_dossier_identity(item) for item in items]
        data["billsStatus"] = "ambiguous"
        return ToolResult(tool="customer_dossier", success=True, data=data)

    try:
        invoices = await context.retailer.get_invoices(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=items[0]["id"],
            limit=_DOSSIER_BILL_CAP,
            include_items=True,
        )
    except RetailerHttpError as exc:
        data["billsStatus"] = "unavailable"
        data["billsError"] = exc.code
        return ToolResult(tool="customer_dossier", success=True, data=data)

    raw_bills = invoices.body.get("data") if isinstance(invoices.body, dict) else None
    bills = _compact_bills(raw_bills if isinstance(raw_bills, list) else [])
    data["bills"] = bills
    data["billsScanned"] = len(bills)
    data["billsStatus"] = "ok" if bills else "empty"
    return ToolResult(tool="customer_dossier", success=True, data=data)


def _narrow_dossier_customers(
    items: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Prefer one exact name, phone, or email over a substring page."""
    needle = query.strip().casefold()
    if len(needle) < 2:
        return items
    exact = [item for item in items if _dossier_exact(item, needle)]
    if exact:
        return exact
    return [item for item in items if _dossier_contains(item, needle)]


def _dossier_exact(item: dict[str, Any], needle: str) -> bool:
    for key in ("name", "phone", "email"):
        value = item.get(key)
        if isinstance(value, str) and value.strip().casefold() == needle:
            return True
    return False


def _dossier_contains(item: dict[str, Any], needle: str) -> bool:
    for key in ("name", "phone", "email"):
        value = item.get(key)
        if isinstance(value, str) and needle in value.casefold():
            return True
    return False


def _dossier_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in ("id", "name", "phone")
        if key in item and item[key] not in (None, "")
    }


def _dossier_customer(item: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(item.get("id") or ""),
        "name": item.get("name"),
        "phone": item.get("phone"),
        "email": item.get("email"),
        "isActive": item.get("isActive"),
    }
    note = item.get("note")
    if isinstance(note, str) and note.strip():
        row["note"] = note.strip()
    account = item.get("account")
    if isinstance(account, dict):
        picked = {
            key: account[key]
            for key in ("totalDue", "totalPaid")
            if key in account
        }
        if picked:
            row["account"] = picked
    return row


def _compact_bills(raw_bills: list[Any]) -> list[dict[str, Any]]:
    bills: list[dict[str, Any]] = []
    for bill in raw_bills[:_DOSSIER_BILL_CAP]:
        if not isinstance(bill, dict):
            continue
        row: dict[str, Any] = {}
        bill_id = bill.get("id") or bill.get("_id")
        if bill_id is not None:
            row["id"] = str(bill_id)
        for key in (
            "invoiceNumber",
            "paymentMode",
            "paymentStatus",
            "invoiceStatus",
            "totalAmount",
        ):
            if key in bill:
                row[key] = bill[key]
        when = bill.get("releasedAt") or bill.get("createdAt")
        if when is not None:
            row["date"] = when if isinstance(when, str) else str(when)
        lines = _compact_bill_lines(bill.get("items"))
        if lines:
            row["items"] = lines
        bills.append(row)
    return bills


def _compact_bill_lines(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    lines: list[dict[str, Any]] = []
    for item in raw_items:
        if len(lines) >= _DOSSIER_LINE_CAP:
            break
        if not isinstance(item, dict):
            continue
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        name = item.get("productName") or product.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        line: dict[str, Any] = {"name": name.strip()}
        qty = item.get("quantity")
        if isinstance(qty, (int, float)) and not isinstance(qty, bool):
            line["qty"] = qty
        lines.append(line)
    return lines


_LEDGER_PREVIEW = 40
_DOWNLOAD_FORMATS = ("csv", "xlsx", "json")
_FULL_PROFILE_RE = re.compile(
    r"poori details|full details|complete details|all details|"
    r"sab details|sab kuch|pura profile|poora profile|entire profile|"
    r"kon he|kaun hai|kaun he|kon hai|who is|ke baare me|ke bare me",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"address|billing|shipping|pincode|pata\b",
    re.IGNORECASE,
)
_GST_RE = re.compile(r"\bgst\b|gstin|company|firm\b", re.IGNORECASE)
_LEDGER_RE = re.compile(
    r"ledger|entries|statement|download|\bcsv\b|\bxlsx\b|\bjson\b|"
    r"line by line|khata lines",
    re.IGNORECASE,
)
_KHATA_RE = re.compile(
    r"khata|khate|udhaar|udhar|baaki|baqi|\bdue\b|\bdues\b|"
    r"\bjama\b|balance|\baccount\b|hisab|kitne bill|kitna paid|"
    r"kitna jama|kitna baaki|total due|total paid",
    re.IGNORECASE,
)


def _slices_for_question(question: str) -> frozenset[str]:
    text = question.strip()
    if not text:
        return frozenset()
    if _FULL_PROFILE_RE.search(text):
        return frozenset({"address", "gst", "khata"})
    slices: set[str] = set()
    if _ADDRESS_RE.search(text):
        slices.add("address")
    if _GST_RE.search(text):
        slices.add("gst")
    if _LEDGER_RE.search(text):
        slices.add("ledger")
    elif _KHATA_RE.search(text):
        slices.add("khata")
    return frozenset(slices)


def _download_options(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options = []
    for item in items:
        customer_id = item.get("id")
        if not isinstance(customer_id, str) or not customer_id:
            continue
        options.append(
            {
                "customerId": customer_id,
                "name": item.get("name") or "customer",
                "formats": list(_DOWNLOAD_FORMATS),
            }
        )
    return options


async def _ledger_for_customer(
    context: ToolContext,
    *,
    store_id: str,
    customer_id: str,
) -> dict[str, Any]:
    try:
        response = await context.retailer.get_customer_ledger_export(
            access_token=context.access_token,
            store_id=store_id,
            customer_id=customer_id,
        )
    except RetailerHttpError as exc:
        return {"entries": [], "code": exc.code, "message": exc.message}

    payload = response.body.get("data")
    if not isinstance(payload, dict):
        return {"entries": [], "totalEntries": 0}
    return _ledger_preview(payload)


def _ledger_preview(payload: dict[str, Any]) -> dict[str, Any]:
    raw_entries = payload.get("entries")
    entries = raw_entries if isinstance(raw_entries, list) else []
    clean = [
        {
            "date": entry.get("date"),
            "debit": entry.get("debit"),
            "credit": entry.get("credit"),
            "balance": entry.get("balance"),
            "notes": entry.get("notes"),
        }
        for entry in entries
        if isinstance(entry, dict)
    ]
    preview = clean[-_LEDGER_PREVIEW:]
    meta = payload.get("meta")
    reported = meta.get("totalEntries") if isinstance(meta, dict) else None
    total_entries = reported if isinstance(reported, int) else len(clean)
    return {
        "openingBalance": payload.get("openingBalance"),
        "closingBalance": payload.get("closingBalance"),
        "totalEntries": total_entries,
        "truncated": total_entries > len(preview),
        "entries": preview,
    }


def _customer_row(item: dict[str, Any], *, slices: frozenset[str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(item.get("id") or ""),
        "name": item.get("name"),
        "phone": item.get("phone"),
        "email": item.get("email"),
        "isActive": item.get("isActive"),
    }
    note = item.get("note")
    if isinstance(note, str) and note.strip():
        row["note"] = note.strip()
    if "gst" in slices:
        row["gstDetail"] = item.get("gstDetail")
        row["companyDetails"] = item.get("companyDetails")
    if "address" in slices:
        row["addresses"] = item.get("addresses") or {}
    if "khata" in slices or "ledger" in slices:
        row["account"] = item.get("account")
    return row


async def payment_history(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_payments(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("payment_history", exc)

    body = response.body
    data: dict[str, Any] = {"items": body.get("data") or []}
    if body.get("pagination") is not None:
        data["pagination"] = body["pagination"]
    return ToolResult(tool="payment_history", success=True, data=data)


async def customer_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_customer_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("customer_summary", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    new_customers = payload.get("newCustomers")
    data: dict[str, Any] = {
        "totalCustomers": payload.get("totalCustomers"),
        "todayCustomers": payload.get("todayCustomers"),
    }
    if isinstance(new_customers, dict):
        data["newCustomers"] = {
            key: new_customers[key]
            for key in (
                "last1Day",
                "last7Days",
                "last15Days",
                "last30Days",
                "last3Months",
                "last6Months",
                "last12Months",
            )
            if key in new_customers
        }

    period_days = arguments.get("periodDays")
    if isinstance(period_days, int) and period_days in {7, 15, 30}:
        try:
            detailed = await context.retailer.get_customer_detailed_analytics(
                access_token=context.access_token,
                store_id=context.store_id,
                period_days=period_days,
            )
        except RetailerHttpError as exc:
            return _failure("customer_summary", exc)
        detail_payload = (
            detailed.body.get("data") if isinstance(detailed.body, dict) else {}
        )
        if isinstance(detail_payload, dict):
            period_out: dict[str, Any] = {"days": period_days}
            summary = detail_payload.get("summary")
            if isinstance(summary, dict):
                period_out["summary"] = {
                    key: summary[key]
                    for key in (
                        "totalCustomers",
                        "todayCustomers",
                        "periodCustomers",
                        "growthRate",
                        "avgDailyCustomers",
                        "maxDailyCustomers",
                        "minDailyCustomers",
                    )
                    if key in summary
                }
            period_meta = detail_payload.get("period")
            if isinstance(period_meta, dict):
                for key in ("startDate", "endDate"):
                    if isinstance(period_meta.get(key), str):
                        period_out[key] = period_meta[key]
            detail_new = detail_payload.get("newCustomers")
            if isinstance(detail_new, dict) and detail_new:
                period_out["newCustomers"] = {
                    key: detail_new[key]
                    for key in (
                        "last1Day",
                        "last7Days",
                        "last15Days",
                        "last30Days",
                        "last3Months",
                        "last6Months",
                        "last12Months",
                    )
                    if key in detail_new
                }
            data["period"] = period_out

    return ToolResult(tool="customer_summary", success=True, data=data)


async def get_customer_ledger(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    if not isinstance(customer_id, str) or not customer_id.strip():
        return ToolResult(
            tool="get_customer_ledger",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "customerId is required",
            },
        )
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 100 else 50
    try:
        response = await context.retailer.get_customer_ledger(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip(),
            limit=limit_val,
        )
    except RetailerHttpError as exc:
        return _failure("get_customer_ledger", exc)

    body = response.body
    data: dict[str, Any] = {
        "customerId": customer_id.strip(),
        "items": body.get("data") or [],
    }
    pagination = body.get("pagination") or (
        body.get("meta", {}).get("pagination")
        if isinstance(body.get("meta"), dict)
        else None
    )
    if pagination is not None:
        data["pagination"] = pagination
    return ToolResult(tool="get_customer_ledger", success=True, data=data)


async def list_customer_accounts(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 100 else 20
    customer_id = arguments.get("customerId")
    has_due = arguments.get("hasDue")
    try:
        response = await context.retailer.list_customer_accounts(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip()
            if isinstance(customer_id, str) and customer_id.strip()
            else None,
            has_due=has_due if isinstance(has_due, bool) else None,
            limit=limit_val,
        )
    except RetailerHttpError as exc:
        return _failure("list_customer_accounts", exc)

    body = response.body
    data: dict[str, Any] = {"items": body.get("data") or []}
    if body.get("pagination") is not None:
        data["pagination"] = body["pagination"]
    return ToolResult(tool="list_customer_accounts", success=True, data=data)


async def get_customer_payment(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    payment_id = arguments.get("paymentId")
    if not isinstance(payment_id, str) or not payment_id.strip():
        return ToolResult(
            tool="get_customer_payment",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "paymentId is required",
            },
        )
    try:
        response = await context.retailer.get_payment(
            access_token=context.access_token,
            store_id=context.store_id,
            payment_id=payment_id.strip(),
        )
    except RetailerHttpError as exc:
        return _failure("get_customer_payment", exc)

    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"payment": data}
    return ToolResult(tool="get_customer_payment", success=True, data=payload)


async def list_payment_reminders(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 100 else 20
    customer_id = arguments.get("customerId")
    try:
        response = await context.retailer.list_payment_reminders(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip()
            if isinstance(customer_id, str) and customer_id.strip()
            else None,
            limit=limit_val,
        )
    except RetailerHttpError as exc:
        return _failure("list_payment_reminders", exc)

    body = response.body
    data: dict[str, Any] = {"items": body.get("data") or []}
    if body.get("pagination") is not None:
        data["pagination"] = body["pagination"]
    return ToolResult(tool="list_payment_reminders", success=True, data=data)


async def invoice_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_invoice_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("invoice_summary", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    amounts = payload.get("amounts") if isinstance(payload.get("amounts"), dict) else {}
    today = payload.get("today") if isinstance(payload.get("today"), dict) else {}
    data: dict[str, Any] = {
        "counts": {
            key: counts[key]
            for key in (
                "totalInvoices",
                "releasedInvoices",
                "draftInvoices",
                "cancelledInvoices",
            )
            if key in counts
        },
        "amounts": {
            key: amounts[key]
            for key in ("totalAmount", "averageOrderValue")
            if key in amounts
        },
        "today": {
            key: today[key]
            for key in ("totalInvoices", "releasedInvoices")
            if key in today
        },
    }

    period_days = arguments.get("periodDays")
    if isinstance(period_days, int) and period_days in {1, 7, 15, 30}:
        try:
            detailed = await context.retailer.get_invoice_detailed_analytics(
                access_token=context.access_token,
                store_id=context.store_id,
                period_days=period_days,
            )
        except RetailerHttpError as exc:
            return _failure("invoice_summary", exc)
        detail_payload = (
            detailed.body.get("data") if isinstance(detailed.body, dict) else {}
        )
        if isinstance(detail_payload, dict):
            period_summary = detail_payload.get("summary")
            period_today = detail_payload.get("today")
            period_meta = detail_payload.get("period")
            period_out: dict[str, Any] = {"days": period_days}
            if isinstance(period_summary, dict):
                period_out["summary"] = {
                    key: period_summary[key]
                    for key in (
                        "totalRevenue",
                        "totalProfit",
                        "totalSales",
                        "avgOrderValue",
                    )
                    if key in period_summary
                }
            if isinstance(period_today, dict):
                period_out["today"] = {
                    key: period_today[key]
                    for key in ("revenue", "profit", "sales")
                    if key in period_today
                }
            if isinstance(period_meta, dict):
                for key in ("startDate", "endDate"):
                    if isinstance(period_meta.get(key), str):
                        period_out[key] = period_meta[key]
            data["period"] = period_out

    return ToolResult(tool="invoice_summary", success=True, data=data)


async def list_stores(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_stores(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("list_stores", exc)

    raw = response.body.get("data")
    if isinstance(raw, dict):
        raw_items = [raw]
    elif isinstance(raw, list):
        raw_items = raw
    else:
        raw_items = []

    stores: list[dict[str, Any]] = []
    active_id = context.store_id
    active_name: str | None = None
    active_category: str | None = None
    active_sub_categories: list[str] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        store_id = str(item.get("id") or item.get("_id") or "").strip()
        name = item.get("name")
        name_str = name.strip() if isinstance(name, str) else None
        category = item.get("category")
        category_str = category.strip() if isinstance(category, str) else None
        raw_subs = item.get("subCategories")
        sub_categories: list[str] = []
        if isinstance(raw_subs, list):
            for sub in raw_subs:
                if isinstance(sub, str) and sub.strip():
                    sub_categories.append(sub.strip())
        raw_tags = item.get("tags")
        tags: list[str] = []
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, str) and tag.strip():
                    tags.append(tag.strip())
        row: dict[str, Any] = {
            "id": store_id,
            "name": name_str,
            "category": category_str,
            "subCategories": sub_categories,
        }
        if tags:
            row["tags"] = tags
        if store_id and store_id == active_id:
            row["active"] = True
            active_name = name_str
            active_category = category_str
            active_sub_categories = sub_categories
        stores.append(row)

    return ToolResult(
        tool="list_stores",
        success=True,
        data={
            "count": len(stores),
            "activeStoreId": active_id,
            "activeStoreName": active_name,
            "activeStoreCategory": active_category,
            "activeStoreSubCategories": active_sub_categories,
            "stores": stores,
        },
    )


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
    "product_summary": product_summary,
    "search_customer": search_customer,
    "customer_dossier": customer_dossier,
    "payment_history": payment_history,
    "list_stores": list_stores,
    "customer_summary": customer_summary,
    "get_customer_ledger": get_customer_ledger,
    "list_customer_accounts": list_customer_accounts,
    "get_customer_payment": get_customer_payment,
    "list_payment_reminders": list_payment_reminders,
    "invoice_summary": invoice_summary,
}
