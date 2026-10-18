from __future__ import annotations

import contextlib
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
        raw_items = await _collect_customers(
            context,
            query=effective_query,
            include_addresses="address" in slices,
            include_account="khata" in slices or "ledger" in slices,
        )
    except RetailerHttpError as exc:
        return _failure("search_customer", exc)

    if not raw_items and effective_query != raw_query:
        clean_name = re.sub(r"\(?[6-9]\d{9}\)?", "", raw_query).strip()
        if clean_name:
            with contextlib.suppress(RetailerHttpError):
                raw_items = await _collect_customers(
                    context,
                    query=clean_name,
                    include_addresses="address" in slices,
                    include_account="khata" in slices or "ledger" in slices,
                )
    ranked_items, match_by = _rank_customers(
        [item for item in raw_items if isinstance(item, dict)],
        effective_query,
    )
    items = [_customer_row(item, slices=slices) for item in ranked_items]
    data: dict[str, Any] = {"items": items, "matchBy": match_by}
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
_CUSTOMER_SEARCH_LIMIT = 100
_CUSTOMER_PAGE_CAP = 5


def _customer_cursor(body: dict[str, Any]) -> str | None:
    meta = body.get("meta")
    pagination = meta.get("pagination") if isinstance(meta, dict) else None
    if not isinstance(pagination, dict):
        raw = body.get("pagination")
        pagination = raw if isinstance(raw, dict) else None
    if not isinstance(pagination, dict):
        return None
    has_next = pagination.get("hasNextPage", pagination.get("hasNext"))
    if has_next is False:
        return None
    cursor = pagination.get("nextCursor")
    if isinstance(cursor, str) and cursor.strip():
        return cursor.strip()
    return None


async def _collect_customers(
    context: ToolContext,
    *,
    query: str,
    include_account: bool,
    include_addresses: bool = False,
) -> list[dict[str, Any]]:
    """Page the name/email search so a later name is not hidden by emails."""
    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(_CUSTOMER_PAGE_CAP):
        response = await context.retailer.get_customers(
            access_token=context.access_token,
            store_id=context.store_id,
            query=query,
            limit=_CUSTOMER_SEARCH_LIMIT,
            include_addresses=include_addresses,
            include_account=include_account,
            next_cursor=cursor,
        )
        body = response.body if isinstance(response.body, dict) else {}
        page = body.get("data") or []
        if isinstance(page, list):
            collected.extend(item for item in page if isinstance(item, dict))
        nxt = _customer_cursor(body)
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        cursor = nxt
    return collected


async def customer_dossier(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        raw_items = await _collect_customers(
            context,
            query=arguments["query"],
            include_account=True,
        )
    except RetailerHttpError as exc:
        return _failure("customer_dossier", exc)
    items = [
        _dossier_customer(item) for item in raw_items if isinstance(item, dict)
    ]
    items, match_by = _rank_customers(items, arguments["query"])
    match_count = len(items)
    data: dict[str, Any] = {
        "query": arguments["query"],
        "matchBy": match_by,
        "items": items,
        "matchCount": match_count,
        "billsScanned": 0,
    }
    if match_count == 0 or match_by == "none":
        data["items"] = []
        data["matchCount"] = 0
        data["billsStatus"] = "no_match"
        return ToolResult(tool="customer_dossier", success=True, data=data)
    # Email hits are a choice list, even when only one address contains the name.
    if match_by == "email" or match_count != 1 or not items[0].get("id"):
        data["items"] = [
            _dossier_identity(item, with_email=match_by == "email") for item in items
        ]
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


_TOP_CUSTOMER_PAGE = 100
_TOP_CUSTOMER_PAGES = 5


async def top_customers(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    raw_limit = arguments.get("limit")
    want = raw_limit if isinstance(raw_limit, int) and 1 <= raw_limit <= 20 else 4
    totals: dict[str, dict[str, Any]] = {}
    scanned = 0
    capped = False
    cursor: str | None = None
    seen: set[str] = set()
    try:
        for _ in range(_TOP_CUSTOMER_PAGES):
            response = await context.retailer.list_invoices(
                access_token=context.access_token,
                store_id=context.store_id,
                limit=_TOP_CUSTOMER_PAGE,
                next_cursor=cursor,
            )
            body = response.body if isinstance(response.body, dict) else {}
            page = body.get("data") or []
            if isinstance(page, list):
                for bill in page:
                    if isinstance(bill, dict) and _add_purchase(totals, bill):
                        scanned += 1
            nxt = _customer_cursor(body)
            if not nxt or nxt in seen:
                break
            seen.add(nxt)
            cursor = nxt
        else:
            capped = True
    except RetailerHttpError as exc:
        return _failure("top_customers", exc)
    ranked = sorted(
        totals.values(), key=lambda row: float(row["total"]), reverse=True
    )
    items: list[dict[str, Any]] = []
    for row in ranked[:want]:
        total = float(row["total"])
        shown = int(total) if total == int(total) else round(total, 2)
        items.append(
            {
                "id": row["id"],
                "name": row["name"],
                "phone": row["phone"],
                "total": shown,
                "bills": row["bills"],
            }
        )
    return ToolResult(
        tool="top_customers",
        success=True,
        data={"items": items, "billsScanned": scanned, "capped": capped},
    )


def _add_purchase(totals: dict[str, dict[str, Any]], bill: dict[str, Any]) -> bool:
    status = bill.get("invoiceStatus")
    if isinstance(status, str) and status != "RELEASED":
        return False
    amount = bill.get("totalAmount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return False
    customer = bill.get("customer") if isinstance(bill.get("customer"), dict) else {}
    customer_id = str(customer.get("id") or "")
    if not customer_id:
        return False
    row = totals.get(customer_id)
    if row is None:
        name = customer.get("name") if isinstance(customer.get("name"), str) else ""
        phone = customer.get("phone") if isinstance(customer.get("phone"), str) else ""
        row = {
            "id": customer_id,
            "name": name.strip() or "customer",
            "phone": phone.strip(),
            "total": 0.0,
            "bills": 0,
        }
        totals[customer_id] = row
    row["total"] = float(row["total"]) + float(amount)
    row["bills"] = int(row["bills"]) + 1
    return True


def _rank_customers(
    items: list[dict[str, Any]], query: str
) -> tuple[list[dict[str, Any]], str]:
    """Name matches win. Email matches are used only when no name matches."""
    needle = query.strip().casefold()
    if len(needle) < 2:
        return items, "name" if items else "none"

    def text(item: dict[str, Any], key: str) -> str:
        value = item.get(key)
        return value.strip().casefold() if isinstance(value, str) else ""

    exact_name = [item for item in items if text(item, "name") == needle]
    partial_name = [
        item
        for item in items
        if item not in exact_name and needle in text(item, "name")
    ]
    if exact_name or partial_name:
        return exact_name + partial_name, "name"
    phone_needle = query.strip()
    exact_phone = [
        item
        for item in items
        if isinstance(item.get("phone"), str) and item["phone"].strip() == phone_needle
    ]
    if exact_phone:
        return exact_phone, "phone"
    email_hits = [
        item
        for item in items
        if needle == text(item, "email") or needle in text(item, "email")
    ]
    if email_hits:
        return email_hits, "email"
    return [], "none"


def _dossier_identity(
    item: dict[str, Any], *, with_email: bool = False
) -> dict[str, Any]:
    keys = ("id", "name", "phone", "email") if with_email else ("id", "name", "phone")
    return {
        key: item[key]
        for key in keys
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
            for key in (
                "totalInvoices",
                "releasedInvoices",
                "revenue",
                "profit",
                "sales",
            )
            if key in today
        },
    }
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if summary:
        data["summary"] = {
            key: summary[key]
            for key in ("totalRevenue", "totalProfit", "totalSales", "avgOrderValue")
            if key in summary
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


async def stock_items(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_stock_items(
            access_token=context.access_token,
            store_id=context.store_id,
            include_services=bool(arguments.get("includeServices")),
        )
    except RetailerHttpError as exc:
        return _failure("stock_items", exc)

    raw_items = response.body.get("data")
    if isinstance(raw_items, dict) and "items" in raw_items:
        raw_items = raw_items["items"]
    if not isinstance(raw_items, list):
        raw_items = []

    items = []
    for item in raw_items[:30]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "id": str(item.get("id") or item.get("_id") or ""),
                "name": item.get("name") or item.get("productName"),
                "sku": item.get("sku"),
                "stock": (
                    item.get("quantity")
                    or item.get("availableQuantity")
                    or item.get("stock")
                ),
                "status": item.get("stockStatus") or item.get("status"),
                "sellingPrice": item.get("sellingPrice") or item.get("price"),
                "purchasePrice": (
                    item.get("purchasePrice") or item.get("costPrice")
                ),
            }
        )
    return ToolResult(
        tool="stock_items",
        success=True,
        data={
            "count": len(items),
            "items": items,
            "coverage": f"scanned {len(items)} items",
        },
    )


async def list_invoices(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 30 else 20
    invoice_status = arguments.get("invoiceStatus")
    payment_status = arguments.get("paymentStatus")
    customer_id = arguments.get("customerId")
    start_date = arguments.get("startDate")
    end_date = arguments.get("endDate")

    try:
        response = await context.retailer.list_invoices(
            access_token=context.access_token,
            store_id=context.store_id,
            limit=limit_val,
            invoice_status=(
                invoice_status
                if isinstance(invoice_status, str)
                else "RELEASED"
            ),
            payment_status=(
                payment_status if isinstance(payment_status, str) else None
            ),
            customer_id=(
                customer_id
                if isinstance(customer_id, str) and customer_id.strip()
                else None
            ),
            start_date=start_date if isinstance(start_date, str) else None,
            end_date=end_date if isinstance(end_date, str) else None,
            include_items=False,
        )
    except RetailerHttpError as exc:
        return _failure("list_invoices", exc)

    payload = response.body.get("data")
    if isinstance(payload, dict) and "invoices" in payload:
        raw_invoices = payload["invoices"]
    elif isinstance(payload, list):
        raw_invoices = payload
    else:
        raw_invoices = []

    invoices = []
    for inv in raw_invoices[:limit_val]:
        if not isinstance(inv, dict):
            continue
        cust = inv.get("customer")
        cust_info = None
        if isinstance(cust, dict):
            cust_info = {
                "id": str(cust.get("id") or cust.get("_id") or ""),
                "name": cust.get("name"),
                "phone": cust.get("phone"),
            }
        elif isinstance(cust, str):
            cust_info = {"id": cust}

        invoices.append(
            {
                "id": str(inv.get("id") or inv.get("_id") or ""),
                "invoiceNumber": inv.get("invoiceNumber"),
                "customer": cust_info,
                "invoiceDate": inv.get("invoiceDate") or inv.get("createdAt"),
                "totalAmount": (
                    inv.get("grandTotal")
                    or inv.get("totalAmount")
                    or inv.get("total")
                ),
                "paymentStatus": inv.get("paymentStatus"),
                "invoiceStatus": inv.get("invoiceStatus") or inv.get("status"),
                "itemCount": (
                    len(inv.get("items", []))
                    if isinstance(inv.get("items"), list)
                    else inv.get("totalItems")
                ),
            }
        )

    return ToolResult(
        tool="list_invoices",
        success=True,
        data={
            "count": len(invoices),
            "invoices": invoices,
            "status": invoice_status or "RELEASED",
        },
    )


async def expense_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_expense_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("expense_summary", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    by_category_raw = (
        payload.get("byCategory") or payload.get("categories") or []
    )
    by_category = (
        by_category_raw[:10] if isinstance(by_category_raw, list) else []
    )

    return ToolResult(
        tool="expense_summary",
        success=True,
        data={
            "totals": {
                k: totals[k]
                for k in (
                    "totalExpenses",
                    "totalAmount",
                    "paidAmount",
                    "pendingAmount",
                )
                if k in totals
            },
            "byCategory": by_category,
        },
    )


async def list_expenses(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 20 else 20
    category = arguments.get("category")
    start_date = arguments.get("startDate")
    end_date = arguments.get("endDate")

    try:
        response = await context.retailer.get_expenses(
            access_token=context.access_token,
            store_id=context.store_id,
            limit=limit_val,
            category=category if isinstance(category, str) else None,
            start_date=start_date if isinstance(start_date, str) else None,
            end_date=end_date if isinstance(end_date, str) else None,
        )
    except RetailerHttpError as exc:
        return _failure("list_expenses", exc)

    payload = response.body.get("data")
    if isinstance(payload, dict) and "expenses" in payload:
        raw_items = payload["expenses"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    expenses = []
    for exp in raw_items[:limit_val]:
        if not isinstance(exp, dict):
            continue
        expenses.append(
            {
                "id": str(exp.get("id") or exp.get("_id") or ""),
                "expenseNumber": exp.get("expenseNumber"),
                "title": (
                    exp.get("title")
                    or exp.get("notes")
                    or exp.get("description")
                ),
                "category": exp.get("category"),
                "amount": exp.get("amount"),
                "paymentMode": exp.get("paymentMode"),
                "date": exp.get("date") or exp.get("createdAt"),
                "status": exp.get("status"),
            }
        )
    return ToolResult(
        tool="list_expenses",
        success=True,
        data={"count": len(expenses), "expenses": expenses},
    )


async def cashbook_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    from_date = arguments.get("fromDate")
    to_date = arguments.get("toDate")
    try:
        response = await context.retailer.get_cashbook_summary(
            access_token=context.access_token,
            store_id=context.store_id,
            from_date=from_date if isinstance(from_date, str) else None,
            to_date=to_date if isinstance(to_date, str) else None,
        )
    except RetailerHttpError as exc:
        return _failure("cashbook_summary", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    summary = {
        "openingBalance": payload.get("openingBalance"),
        "closingBalance": payload.get("closingBalance"),
        "totalCashIn": payload.get("totalCashIn") or payload.get("cashIn"),
        "totalCashOut": payload.get("totalCashOut") or payload.get("cashOut"),
        "netBalance": (
            payload.get("netBalance") or payload.get("currentBalance")
        ),
        "cashSales": payload.get("cashSales"),
        "dayStatus": payload.get("dayStatus") or payload.get("status"),
    }
    return ToolResult(
        tool="cashbook_summary",
        success=True,
        data={k: v for k, v in summary.items() if v is not None},
    )


async def search_supplier(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    query = arguments.get("query", "").strip()
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 20 else 10

    try:
        response = await context.retailer.get_suppliers(
            access_token=context.access_token,
            store_id=context.store_id,
            query=query,
            limit=limit_val,
            include_account=True,
        )
    except RetailerHttpError as exc:
        return _failure("search_supplier", exc)

    payload = response.body.get("data")
    if isinstance(payload, dict) and "suppliers" in payload:
        raw_items = payload["suppliers"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    suppliers = []
    for s in raw_items[:limit_val]:
        if not isinstance(s, dict):
            continue
        acc = s.get("account") if isinstance(s.get("account"), dict) else {}
        suppliers.append(
            {
                "id": str(s.get("id") or s.get("_id") or ""),
                "name": s.get("name"),
                "phone": s.get("phone"),
                "email": s.get("email"),
                "companyName": s.get("companyName") or s.get("company"),
                "gstNumber": s.get("gstNumber") or s.get("gstin"),
                "totalDue": acc.get("totalDue") or s.get("totalDue") or 0.0,
            }
        )
    return ToolResult(
        tool="search_supplier",
        success=True,
        data={"count": len(suppliers), "suppliers": suppliers},
    )


async def supplier_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_supplier_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("supplier_summary", exc)

    payload = (
        response.body.get("data") if isinstance(response.body, dict) else {}
    )
    if not isinstance(payload, dict):
        payload = {}

    totals = (
        payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    )
    counts = (
        payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    )
    merged_counts = {**totals, **counts}

    bill_amounts: dict[str, Any] = (
        payload.get("amounts")
        if isinstance(payload.get("amounts"), dict)
        else {}
    )
    bill_counts: dict[str, Any] = {}
    if not bill_amounts:
        try:
            bill_res = await context.retailer.get_bill_analytics(
                access_token=context.access_token,
                store_id=context.store_id,
            )
            b_data = (
                bill_res.body.get("data")
                if isinstance(bill_res.body, dict)
                else {}
            )
            if isinstance(b_data, dict):
                raw_amt = b_data.get("amounts")
                if isinstance(raw_amt, dict):
                    bill_amounts = {
                        k: raw_amt[k]
                        for k in ("totalPayable", "totalPaid", "totalDue")
                        if k in raw_amt
                    }
                raw_cnt = b_data.get("counts")
                if isinstance(raw_cnt, dict):
                    bill_counts = {
                        k: raw_cnt[k]
                        for k in ("totalBills", "pendingBills", "overdueBills")
                        if k in raw_cnt
                    }
        except Exception:
            pass

    return ToolResult(
        tool="supplier_summary",
        success=True,
        data={
            "counts": {
                k: merged_counts[k]
                for k in (
                    "totalSuppliers",
                    "activeSuppliers",
                    "inactiveSuppliers",
                    "withDues",
                )
                if k in merged_counts
            },
            "amounts": bill_amounts,
            "bills": bill_counts,
        },
    )



async def list_purchase_orders(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 20 else 20
    status = arguments.get("status")
    supplier_id = arguments.get("supplierId")

    try:
        response = await context.retailer.get_purchase_orders(
            access_token=context.access_token,
            store_id=context.store_id,
            limit=limit_val,
            status=status if isinstance(status, str) else None,
            supplier_id=(
                supplier_id
                if isinstance(supplier_id, str) and supplier_id.strip()
                else None
            ),
        )
    except RetailerHttpError as exc:
        return _failure("list_purchase_orders", exc)

    payload = response.body.get("data")
    if isinstance(payload, dict) and "purchaseOrders" in payload:
        raw_items = payload["purchaseOrders"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    pos = []
    for po in raw_items[:limit_val]:
        if not isinstance(po, dict):
            continue
        supp = po.get("supplier")
        supp_info = None
        if isinstance(supp, dict):
            supp_info = {
                "id": str(supp.get("id") or supp.get("_id") or ""),
                "name": supp.get("name"),
            }
        elif isinstance(supp, str):
            supp_info = {"id": supp}

        pos.append(
            {
                "id": str(po.get("id") or po.get("_id") or ""),
                "poNumber": po.get("poNumber"),
                "supplier": supp_info,
                "poDate": po.get("poDate") or po.get("createdAt"),
                "status": po.get("status"),
                "approvalStatus": po.get("approvalStatus"),
                "totalAmount": po.get("totalAmount") or po.get("grandTotal"),
                "itemCount": (
                    len(po.get("items", []))
                    if isinstance(po.get("items"), list)
                    else 0
                ),
            }
        )

    return ToolResult(
        tool="list_purchase_orders",
        success=True,
        data={"count": len(pos), "purchaseOrders": pos},
    )


async def bill_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_bill_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("bill_summary", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    amounts = payload.get("amounts") if isinstance(payload.get("amounts"), dict) else {}

    return ToolResult(
        tool="bill_summary",
        success=True,
        data={
            "counts": {
                k: counts[k]
                for k in (
                    "totalBills",
                    "paidBills",
                    "pendingBills",
                    "overdueBills",
                )
                if k in counts
            },
            "amounts": {
                k: amounts[k]
                for k in ("totalPayable", "totalPaid", "totalDue", "totalGst")
                if k in amounts
            },
        },
    )


async def gst_summary(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    month = arguments.get("month")
    quarter = arguments.get("quarter")
    year = arguments.get("year")
    period = arguments.get("period")

    try:
        summary_res = await context.retailer.get_gst_summary(
            access_token=context.access_token,
            store_id=context.store_id,
            month=month if isinstance(month, str) else None,
            quarter=quarter if isinstance(quarter, str) else None,
            year=year if isinstance(year, str) else None,
            period=period if isinstance(period, str) else None,
        )
    except RetailerHttpError as exc:
        return _failure("gst_summary", exc)

    payload = (
        summary_res.body.get("data")
        if isinstance(summary_res.body, dict)
        else {}
    )
    if not isinstance(payload, dict):
        payload = {}

    health_score = None
    try:
        health_res = await context.retailer.get_gst_health_score(
            access_token=context.access_token,
            store_id=context.store_id,
            month=month if isinstance(month, str) else None,
            quarter=quarter if isinstance(quarter, str) else None,
            year=year if isinstance(year, str) else None,
        )
        h_data = health_res.body.get("data")
        if isinstance(h_data, dict):
            health_score = h_data.get("healthScore") or h_data.get("score")
    except Exception:
        health_score = None

    data = {
        "period": payload.get("period"),
        "totalTaxableAmount": (
            payload.get("totalTaxableAmount") or payload.get("taxableAmount")
        ),
        "totalTax": payload.get("totalTax") or payload.get("taxAmount"),
        "cgst": payload.get("cgst"),
        "sgst": payload.get("sgst"),
        "igst": payload.get("igst"),
        "invoiceCount": (
            payload.get("invoiceCount") or payload.get("totalInvoices")
        ),
    }
    if health_score is not None:
        data["healthScore"] = health_score

    return ToolResult(
        tool="gst_summary",
        success=True,
        data={k: v for k, v in data.items() if v is not None},
    )


async def list_sales_orders(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    limit = arguments.get("limit")
    limit_val = limit if isinstance(limit, int) and 1 <= limit <= 20 else 20
    status = arguments.get("status")
    customer_id = arguments.get("customerId")

    try:
        response = await context.retailer.get_sales_orders(
            access_token=context.access_token,
            store_id=context.store_id,
            limit=limit_val,
            status=status if isinstance(status, str) else None,
            customer_id=(
                customer_id
                if isinstance(customer_id, str) and customer_id.strip()
                else None
            ),
        )
    except RetailerHttpError as exc:
        return _failure("list_sales_orders", exc)

    payload = response.body.get("data")
    if isinstance(payload, dict) and "orders" in payload:
        raw_items = payload["orders"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    orders = []
    for order in raw_items[:limit_val]:
        if not isinstance(order, dict):
            continue
        cust = order.get("customer")
        cust_info = None
        if isinstance(cust, dict):
            cust_info = {
                "id": str(cust.get("id") or cust.get("_id") or ""),
                "name": cust.get("name"),
                "phone": cust.get("phone"),
            }
        elif isinstance(cust, str):
            cust_info = {"id": cust}

        orders.append(
            {
                "id": str(order.get("id") or order.get("_id") or ""),
                "orderNumber": (
                    order.get("orderNumber") or order.get("publicId")
                ),
                "customer": cust_info,
                "orderDate": order.get("orderDate") or order.get("createdAt"),
                "status": order.get("status"),
                "paymentStatus": order.get("paymentStatus"),
                "totalAmount": order.get("totalAmount"),
            }
        )

    return ToolResult(
        tool="list_sales_orders",
        success=True,
        data={"count": len(orders), "salesOrders": orders},
    )


async def list_staff(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    try:
        response = await context.retailer.get_staff(
            access_token=context.access_token,
            store_id=context.store_id,
        )
    except RetailerHttpError as exc:
        return _failure("list_staff", exc)

    payload = response.body.get("data")
    if isinstance(payload, dict) and "staff" in payload:
        raw_items = payload["staff"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    staff_members = []
    for m in raw_items[:20]:
        if not isinstance(m, dict):
            continue
        user_info = m.get("user") if isinstance(m.get("user"), dict) else {}
        name = m.get("name") or user_info.get("name")
        phone = m.get("phone") or user_info.get("phone")
        staff_members.append(
            {
                "id": str(m.get("id") or m.get("_id") or ""),
                "name": name,
                "phone": phone,
                "role": m.get("role") or m.get("roleName"),
                "status": m.get("status") or "ACTIVE",
            }
        )

    return ToolResult(
        tool="list_staff",
        success=True,
        data={"count": len(staff_members), "staff": staff_members},
    )


async def customer_detailed_analytics(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    period_days = arguments.get("periodDays", 30)
    analytics_type = arguments.get("analyticsType", "overview")
    try:
        response = await context.retailer.get_customer_detailed_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
            period_days=period_days,
            analytics_type=analytics_type,
        )
    except RetailerHttpError as exc:
        return _failure("customer_detailed_analytics", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    return ToolResult(
        tool="customer_detailed_analytics",
        success=True,
        data=payload if isinstance(payload, dict) else {},
    )


async def invoice_detailed_analytics(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    period_days = arguments.get("periodDays", 30)
    try:
        response = await context.retailer.get_invoice_detailed_analytics(
            access_token=context.access_token,
            store_id=context.store_id,
            period_days=period_days,
        )
    except RetailerHttpError as exc:
        return _failure("invoice_detailed_analytics", exc)

    payload = response.body.get("data") if isinstance(response.body, dict) else {}
    return ToolResult(
        tool="invoice_detailed_analytics",
        success=True,
        data=payload if isinstance(payload, dict) else {},
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
    "top_customers": top_customers,
    "payment_history": payment_history,
    "list_stores": list_stores,
    "customer_summary": customer_summary,
    "get_customer_ledger": get_customer_ledger,
    "list_customer_accounts": list_customer_accounts,
    "get_customer_payment": get_customer_payment,
    "list_payment_reminders": list_payment_reminders,
    "invoice_summary": invoice_summary,
    "stock_items": stock_items,
    "list_invoices": list_invoices,
    "expense_summary": expense_summary,
    "list_expenses": list_expenses,
    "cashbook_summary": cashbook_summary,
    "search_supplier": search_supplier,
    "supplier_summary": supplier_summary,
    "list_purchase_orders": list_purchase_orders,
    "bill_summary": bill_summary,
    "gst_summary": gst_summary,
    "list_sales_orders": list_sales_orders,
    "list_staff": list_staff,
    "customer_detailed_analytics": customer_detailed_analytics,
    "invoice_detailed_analytics": invoice_detailed_analytics,
}
