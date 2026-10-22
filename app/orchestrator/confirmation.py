"""Helpers to stage invoice-release confirmations without bloating ChatService."""

from __future__ import annotations

import uuid
from typing import Any

from app.confirmations import (
    CONFIRMATION_TYPE_ADD_STOCK,
    CONFIRMATION_TYPE_CREATE_COLLECT_LINK,
    CONFIRMATION_TYPE_CREATE_EXPENSE,
    CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER,
    CONFIRMATION_TYPE_INVOICE_RELEASE,
    CONFIRMATION_TYPE_LEDGER_CREDIT,
    CONFIRMATION_TYPE_LEDGER_DEBIT,
    CONFIRMATION_TYPE_MERGE_CUSTOMERS,
    CONFIRMATION_TYPE_RECORD_CUSTOMER_PAYMENT,
    CONFIRMATION_TYPE_SEND_PAYMENT_REMINDER,
    CONFIRMATION_TYPE_SET_OPENING_BALANCE,
    CONFIRMATION_TYPE_UPDATE_CUSTOMER_PAYMENT,
    ConfirmationStore,
    PendingConfirmationRecord,
    normalize_expense_category,
)
from app.core.dates import resolve_expense_date
from app.core.exceptions import AppError
from app.integrations.retailer_client import RetailerClient, RetailerHttpError
from app.observability.audit_trail import AuditTrail
from app.observability.confirmation_audit import audit_confirmation
from app.observability.metrics import MetricsRegistry
from app.schemas.chat import PendingConfirmation
from app.schemas.tool import ToolCall, ToolResult

_CUSTOMER_SENSITIVE_TOOLS = frozenset(
    {
        CONFIRMATION_TYPE_MERGE_CUSTOMERS,
        CONFIRMATION_TYPE_SET_OPENING_BALANCE,
        CONFIRMATION_TYPE_RECORD_CUSTOMER_PAYMENT,
        CONFIRMATION_TYPE_UPDATE_CUSTOMER_PAYMENT,
        CONFIRMATION_TYPE_CREATE_COLLECT_LINK,
        CONFIRMATION_TYPE_SEND_PAYMENT_REMINDER,
    }
)


def _audit_pending(
    record: PendingConfirmationRecord,
    *,
    audit_trail: AuditTrail | None,
    metrics: MetricsRegistry | None,
) -> None:
    audit_confirmation(
        audit_trail=audit_trail,
        metrics=metrics,
        confirmation_id=record.confirmation_id,
        type=record.type,
        status="PENDING",
        previous_status=None,
        user_id=record.user_id,
        store_id=record.store_id,
        session_id=record.session_id,
        tool=record.tool_name,
        business_idempotency_key=record.business_idempotency_key,
    )


def pending_to_schema(record: PendingConfirmationRecord) -> PendingConfirmation:
    return PendingConfirmation(
        confirmation_id=record.confirmation_id,
        type=record.type,
        draft_id=record.draft_id,
        summary=dict(record.summary),
        expires_at=record.to_public()["expiresAt"],
    )


def extract_invoice_id(data: dict[str, Any] | None) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("id", "_id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    invoice = data.get("invoice")
    if isinstance(invoice, dict):
        for key in ("id", "_id"):
            value = invoice.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def build_invoice_summary(data: dict[str, Any] | None) -> dict[str, Any]:
    """Build a client preview from retailer draft payload — never invent totals."""
    summary: dict[str, Any] = {"currency": "INR"}
    if not isinstance(data, dict):
        return summary
    invoice = data.get("invoice") if isinstance(data.get("invoice"), dict) else data
    if not isinstance(invoice, dict):
        return summary
    for key, _alias in (
        ("totalAmount", "total"),
        ("grandTotal", "total"),
        ("total", "total"),
        ("payableAmount", "total"),
    ):
        value = invoice.get(key)
        if isinstance(value, (int, float)):
            summary["total"] = value
            break
    invoice_number = invoice.get("invoiceNumber") or invoice.get("number")
    if isinstance(invoice_number, str) and invoice_number.strip():
        summary["invoiceNumber"] = invoice_number.strip()
    open_path = data.get("openPath")
    if isinstance(open_path, str) and open_path.strip():
        summary["openPath"] = open_path.strip()
    return summary


async def stage_from_draft_result(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    result: ToolResult,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
) -> PendingConfirmationRecord | None:
    # Draft update refreshes the pending confirmation too — customer link
    # changes GST/totals, so the preview must show fresh numbers.
    if result.tool not in {"create_invoice_draft", "update_invoice_draft"}:
        return None
    if not result.success:
        return None
    draft_id = extract_invoice_id(result.data)
    if draft_id is None:
        return None
    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=draft_id,
        summary=build_invoice_summary(result.data),
        tool_name="release_invoice",
        arguments={"storeId": store_id, "invoiceId": draft_id},
    )
    _audit_pending(
        record,
        audit_trail=audit_trail,
        metrics=metrics,
    )
    return record


async def stage_from_sensitive_calls(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    sensitive_calls: list[ToolCall],
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
    retailer: RetailerClient | None = None,
    access_token: str | None = None,
    question: str = "",
) -> PendingConfirmationRecord | None:
    """Stage at most one SENSITIVE confirmation per turn."""
    if not sensitive_calls:
        return None
    if len(sensitive_calls) > 1:
        raise AppError(
            code="CONFIRMATION_REQUIRED",
            message="Only one sensitive action can be confirmed per turn",
            status_code=400,
        )
    call = sensitive_calls[0]
    if call.name in {CONFIRMATION_TYPE_LEDGER_CREDIT, CONFIRMATION_TYPE_LEDGER_DEBIT}:
        return await _stage_ledger_call(
            store,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            call=call,
            audit_trail=audit_trail,
            metrics=metrics,
        )
    if call.name == CONFIRMATION_TYPE_ADD_STOCK:
        return await _stage_add_stock_call(
            store,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            call=call,
            audit_trail=audit_trail,
            metrics=metrics,
            retailer=retailer,
            access_token=access_token,
        )
    if call.name in _CUSTOMER_SENSITIVE_TOOLS:
        return await _stage_customer_sensitive_call(
            store,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            call=call,
            audit_trail=audit_trail,
            metrics=metrics,
        )
    if call.name == CONFIRMATION_TYPE_CREATE_EXPENSE:
        return await _stage_create_expense_call(
            store,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            call=call,
            audit_trail=audit_trail,
            metrics=metrics,
            question=question,
        )
    if call.name == CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER:
        return await _stage_create_purchase_order_call(
            store,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            call=call,
            audit_trail=audit_trail,
            metrics=metrics,
            retailer=retailer,
            access_token=access_token,
        )
    if call.name != "release_invoice":
        raise AppError(
            code="TOOL_NOT_EXECUTABLE",
            message=f"Sensitive tool '{call.name}' is not supported",
            status_code=400,
        )
    invoice_id = call.arguments.get("invoiceId")
    if not isinstance(invoice_id, str) or not invoice_id.strip():
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="release_invoice requires invoiceId",
            status_code=400,
        )
    invoice_id = invoice_id.strip()
    summary: dict[str, Any] = {
        "currency": "INR",
        "openPath": f"/dashboard/invoices/{invoice_id}",
    }
    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=invoice_id,
        summary=summary,
        tool_name="release_invoice",
        arguments={
            "storeId": store_id,
            "invoiceId": invoice_id,
            **{
                k: v
                for k, v in call.arguments.items()
                if k in {"paymentStatus", "paidAmount", "paymentMode"}
            },
        },
    )
    _audit_pending(record, audit_trail=audit_trail, metrics=metrics)
    return record


def _positive_amount(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    if isinstance(value, int):
        return value
    return float(value)


def _non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return float(value)


def _stock_qty_from_inventory_payload(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    # Paginated list: { items: [ { stockSummary / availableQuantity } ] }
    items = data.get("items") or data.get("inventories") or data.get("data")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            return _qty_from_inventory_row(first)
    inventory = data.get("inventory")
    if isinstance(inventory, dict):
        return _qty_from_inventory_row(inventory)
    return _qty_from_inventory_row(data)


def _qty_from_inventory_row(row: dict[str, Any]) -> float | None:
    summary = row.get("stockSummary")
    if isinstance(summary, dict):
        for key in ("availableQuantity", "totalQuantity"):
            value = _non_negative_number(summary.get(key))
            if value is not None:
                return value
    for key in ("availableQuantity", "totalQuantity", "stock"):
        value = row.get(key)
        if isinstance(value, dict):
            nested = _non_negative_number(
                value.get("availableQuantity") or value.get("totalQuantity")
            )
            if nested is not None:
                return nested
        qty = _non_negative_number(value)
        if qty is not None:
            return qty
    return None


async def _lookup_current_stock(
    *,
    retailer: RetailerClient | None,
    access_token: str | None,
    store_id: str,
    product_id: str,
) -> float | None:
    if retailer is None or not access_token:
        return None
    try:
        response = await retailer.get_inventory(
            access_token=access_token,
            store_id=store_id,
            product_id=product_id,
        )
    except RetailerHttpError:
        return None
    return _stock_qty_from_inventory_payload(response.body)


async def _stage_add_stock_call(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    call: ToolCall,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
    retailer: RetailerClient | None = None,
    access_token: str | None = None,
) -> PendingConfirmationRecord:
    raw_items = call.arguments.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="add_stock requires a non-empty items array",
            status_code=400,
        )
    if len(raw_items) > 10:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="add_stock supports at most 10 items per confirm",
            status_code=400,
        )

    staged_items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="each add_stock item must be an object",
                status_code=400,
            )
        product_id = raw.get("productId")
        if not isinstance(product_id, str) or not product_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="add_stock items require productId",
                status_code=400,
            )
        quantity = _positive_amount(raw.get("quantity"))
        if quantity is None:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="add_stock items require quantity > 0",
                status_code=400,
            )
        product_id = product_id.strip()
        current = _non_negative_number(raw.get("currentStock"))
        if current is None:
            current = await _lookup_current_stock(
                retailer=retailer,
                access_token=access_token,
                store_id=store_id,
                product_id=product_id,
            )
        if current is None:
            current = 0.0
        purchase_price = _positive_amount(raw.get("purchasePrice"))
        if purchase_price is None:
            purchase_price = 1.0
        line: dict[str, Any] = {
            "productId": product_id,
            "quantity": quantity,
            "purchasePrice": purchase_price,
            "currentStock": current,
            "adding": quantity,
            "finalStock": current + float(quantity),
        }
        name = raw.get("productName")
        if isinstance(name, str) and name.strip():
            line["productName"] = name.strip()
        source = raw.get("sourceName")
        if isinstance(source, str) and source.strip():
            line["sourceName"] = source.strip()
        staged_items.append(line)

    draft_id = staged_items[0]["productId"]
    summary: dict[str, Any] = {
        "action": "add_stock",
        "items": [
            {
                "productId": item["productId"],
                "productName": item.get("productName"),
                "sourceName": item.get("sourceName"),
                "currentStock": item["currentStock"],
                "adding": item["adding"],
                "finalStock": item["finalStock"],
            }
            for item in staged_items
        ],
        "count": len(staged_items),
    }
    arguments: dict[str, Any] = {
        "storeId": store_id,
        "items": [
            {
                "productId": item["productId"],
                "quantity": item["quantity"],
                "purchasePrice": item["purchasePrice"],
                "currentStock": item["currentStock"],
                **(
                    {"productName": item["productName"]}
                    if "productName" in item
                    else {}
                ),
                **({"sourceName": item["sourceName"]} if "sourceName" in item else {}),
            }
            for item in staged_items
        ],
    }
    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=CONFIRMATION_TYPE_ADD_STOCK,
        draft_id=draft_id,
        summary=summary,
        tool_name="add_stock",
        arguments=arguments,
    )
    _audit_pending(record, audit_trail=audit_trail, metrics=metrics)
    return record


async def _stage_customer_sensitive_call(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    call: ToolCall,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
) -> PendingConfirmationRecord:
    """Stage merge / opening balance / payment / collect / reminder."""
    args = dict(call.arguments)
    args["storeId"] = store_id
    summary: dict[str, Any] = {"currency": "INR"}
    draft_id: str

    if call.name == CONFIRMATION_TYPE_MERGE_CUSTOMERS:
        primary_id = args.get("primaryId")
        duplicate_id = args.get("duplicateId")
        if not isinstance(primary_id, str) or not primary_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="merge_customers requires primaryId",
                status_code=400,
            )
        if not isinstance(duplicate_id, str) or not duplicate_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="merge_customers requires duplicateId",
                status_code=400,
            )
        primary_id = primary_id.strip()
        duplicate_id = duplicate_id.strip()
        if primary_id == duplicate_id:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="primaryId and duplicateId must differ",
                status_code=400,
            )
        args["primaryId"] = primary_id
        args["duplicateId"] = duplicate_id
        draft_id = primary_id
        summary.update(
            {
                "action": "merge",
                "primaryId": primary_id,
                "duplicateId": duplicate_id,
                "openPath": f"/dashboard/customers/{primary_id}",
            }
        )
    elif call.name == CONFIRMATION_TYPE_SET_OPENING_BALANCE:
        customer_id = args.get("customerId")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="set_opening_balance requires customerId",
                status_code=400,
            )
        customer_id = customer_id.strip()
        args["customerId"] = customer_id
        draft_id = customer_id
        summary.update(
            {
                "action": "opening_balance",
                "customerId": customer_id,
                "openPath": f"/dashboard/customers/{customer_id}",
            }
        )
        for key in ("totalDue", "totalPaid", "totalAmount"):
            amount = _non_negative_number(args.get(key))
            if amount is not None:
                args[key] = amount
                summary[key] = amount
        notes = args.get("notes")
        if isinstance(notes, str) and notes.strip():
            args["notes"] = notes.strip()
    elif call.name == CONFIRMATION_TYPE_RECORD_CUSTOMER_PAYMENT:
        customer_id = args.get("customerId")
        payment = args.get("payment")
        payment_type = args.get("paymentType")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="record_customer_payment requires customerId",
                status_code=400,
            )
        if not isinstance(payment_type, str) or not payment_type.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="record_customer_payment requires paymentType",
                status_code=400,
            )
        if not isinstance(payment, list) or not payment:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="record_customer_payment requires payment[]",
                status_code=400,
            )
        customer_id = customer_id.strip()
        args["customerId"] = customer_id
        args["paymentType"] = payment_type.strip().upper()
        total = 0.0
        for row in payment:
            if not isinstance(row, dict):
                continue
            amt = _positive_amount(row.get("amount"))
            if amt is not None:
                total += float(amt)
        draft_id = customer_id
        summary.update(
            {
                "action": "payment",
                "customerId": customer_id,
                "paymentType": args["paymentType"],
                "total": total,
                "openPath": f"/dashboard/customers/{customer_id}",
            }
        )
    elif call.name == CONFIRMATION_TYPE_UPDATE_CUSTOMER_PAYMENT:
        payment_id = args.get("paymentId")
        notes = args.get("notes")
        if not isinstance(payment_id, str) or not payment_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="update_customer_payment requires paymentId",
                status_code=400,
            )
        if not isinstance(notes, str):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="update_customer_payment requires notes",
                status_code=400,
            )
        payment_id = payment_id.strip()
        args["paymentId"] = payment_id
        args["notes"] = notes
        draft_id = payment_id
        summary.update({"action": "update_payment", "paymentId": payment_id})
    elif call.name == CONFIRMATION_TYPE_CREATE_COLLECT_LINK:
        customer_id = args.get("customerId")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="create_collect_link requires customerId",
                status_code=400,
            )
        customer_id = customer_id.strip()
        args["customerId"] = customer_id
        draft_id = customer_id
        amount = _positive_amount(args.get("amount"))
        summary.update(
            {
                "action": "collect_link",
                "customerId": customer_id,
                "openPath": f"/dashboard/customers/{customer_id}",
            }
        )
        if amount is not None:
            args["amount"] = amount
            summary["total"] = amount
    else:  # send_payment_reminder
        customer_id = args.get("customerId")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="send_payment_reminder requires customerId",
                status_code=400,
            )
        customer_id = customer_id.strip()
        args["customerId"] = customer_id
        draft_id = customer_id
        channel = args.get("channel")
        if isinstance(channel, str) and channel.strip():
            args["channel"] = channel.strip().upper()
        summary.update(
            {
                "action": "payment_reminder",
                "customerId": customer_id,
                "channel": args.get("channel", "EMAIL"),
                "openPath": f"/dashboard/customers/{customer_id}",
            }
        )

    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=call.name,
        draft_id=draft_id,
        summary=summary,
        tool_name=call.name,
        arguments=args,
    )
    _audit_pending(record, audit_trail=audit_trail, metrics=metrics)
    return record


async def _stage_ledger_call(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    call: ToolCall,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
) -> PendingConfirmationRecord:
    customer_id = call.arguments.get("customerId")
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message=f"{call.name} requires customerId",
            status_code=400,
        )
    amount = _positive_amount(call.arguments.get("amount"))
    if amount is None:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message=f"{call.name} requires amount greater than 0",
            status_code=400,
        )
    customer_id = customer_id.strip()
    action = "payment" if call.name == "ledger_credit" else "debit"
    arguments: dict[str, Any] = {
        "storeId": store_id,
        "customerId": customer_id,
        "amount": amount,
    }
    notes = call.arguments.get("notes")
    if isinstance(notes, str) and notes.strip():
        arguments["notes"] = notes.strip()
    confirmation_type = (
        CONFIRMATION_TYPE_LEDGER_CREDIT
        if call.name == "ledger_credit"
        else CONFIRMATION_TYPE_LEDGER_DEBIT
    )
    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=confirmation_type,
        draft_id=customer_id,
        summary={
            "currency": "INR",
            "total": amount,
            "action": action,
            "customerId": customer_id,
        },
        tool_name=call.name,
        arguments=arguments,
    )
    _audit_pending(record, audit_trail=audit_trail, metrics=metrics)
    return record


async def _stage_create_expense_call(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    call: ToolCall,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
    question: str = "",
) -> PendingConfirmationRecord:
    import uuid

    args = dict(call.arguments)
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="create_expense requires title",
            status_code=400,
        )
    amount = _positive_amount(args.get("amount"))
    if amount is None:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="create_expense requires amount > 0",
            status_code=400,
        )
    title = title.strip()
    category_key, category_label = normalize_expense_category(
        args.get("category"), title=title
    )
    context_text = f"{question} {title}".strip()
    resolved_date = resolve_expense_date(args.get("date"), context_text=context_text)

    raw_status = args.get("status")
    if isinstance(raw_status, str) and raw_status.strip().upper() in {
        "PAID",
        "PENDING",
        "OVERDUE",
        "CANCELLED",
    }:
        initial_status = raw_status.strip().upper()
    else:
        q_lower = context_text.lower()
        if any(w in q_lower for w in ("bhra", "paid", "de diya", "clear")):
            initial_status = "PAID"
        elif any(w in q_lower for w in ("baaki", "due", "pending", "unpaid")):
            initial_status = "PENDING"
        else:
            initial_status = "PAID"

    args["title"] = title
    args["amount"] = amount
    args["category"] = category_key
    args["date"] = resolved_date
    args["storeId"] = store_id
    args["status"] = initial_status

    draft_id = f"exp_{uuid.uuid4().hex[:8]}"

    summary: dict[str, Any] = {
        "action": "create_expense",
        "prompt": "Record this expense",
        "title": title,
        "amount": amount,
        "total": amount,
        "invoiceNumber": title,
        "category": category_key,
        "categoryLabel": category_label,
        "date": resolved_date,
        "currency": "INR",
        "status": initial_status,
        "statusOptions": ["PENDING", "PAID", "OVERDUE"],
    }
    desc = (
        args.get("description")
        if isinstance(args.get("description"), str) and args["description"].strip()
        else args.get("notes")
        if isinstance(args.get("notes"), str) and args["notes"].strip()
        else None
    )
    if desc:
        clean_desc = desc.strip()
        args["description"] = clean_desc
        args["notes"] = clean_desc
        summary["description"] = clean_desc
        summary["notes"] = clean_desc

    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=CONFIRMATION_TYPE_CREATE_EXPENSE,
        draft_id=draft_id,
        summary=summary,
        tool_name=call.name,
        arguments=args,
    )
    _audit_pending(record, audit_trail=audit_trail, metrics=metrics)
    return record


async def _stage_create_purchase_order_call(
    store: ConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    call: ToolCall,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
    retailer: RetailerClient | None = None,
    access_token: str | None = None,
) -> PendingConfirmationRecord:
    args = dict(call.arguments)
    supplier_id = args.get("supplierId")
    if not isinstance(supplier_id, str) or not supplier_id.strip():
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="create_purchase_order requires supplierId",
            status_code=400,
        )
    supplier_id = supplier_id.strip()

    raw_items = args.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="create_purchase_order requires at least one item",
            status_code=400,
        )
    sanitized_items: list[dict[str, Any]] = []
    total_qty = 0
    total_amount = 0.0

    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message=f"create_purchase_order item at index {idx} must be an object",
                status_code=400,
            )
        product_id = raw.get("productId")
        if not isinstance(product_id, str) or not product_id.strip():
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message=f"create_purchase_order item at index {idx} requires productId",
                status_code=400,
            )
        product_id = product_id.strip()
        if product_id == supplier_id:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message=(
                    f"create_purchase_order item at index {idx} has productId equal to "
                    f"supplierId ({product_id}). "
                    "A valid product ObjectId from search_product is required."
                ),
                status_code=400,
            )
        qty = raw.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message=(
                    f"create_purchase_order item at index {idx} "
                    "requires positive integer quantity"
                ),
                status_code=400,
            )
        item_entry: dict[str, Any] = {
            "productId": product_id,
            "quantity": qty,
        }
        if isinstance(raw.get("productName"), str) and raw["productName"].strip():
            item_entry["productName"] = raw["productName"].strip()
        if isinstance(raw.get("unit"), str) and raw["unit"].strip():
            item_entry["unit"] = raw["unit"].strip()

        price_val = (
            raw.get("purchasePrice")
            if "purchasePrice" in raw
            else raw.get("price")
            if "price" in raw
            else raw.get("unitPrice")
        )
        if (
            isinstance(price_val, (int, float))
            and not isinstance(price_val, bool)
            and price_val > 0
        ):
            item_entry["purchasePrice"] = float(price_val)
            item_entry["totalPrice"] = round(float(price_val) * qty, 2)
            total_amount += item_entry["totalPrice"]

        sanitized_items.append(item_entry)
        total_qty += qty

    supplier_name = (
        args["supplierName"].strip()
        if isinstance(args.get("supplierName"), str) and args["supplierName"].strip()
        else "Supplier"
    )

    if retailer is not None and access_token:
        if supplier_name == "Supplier":
            try:
                sup_res = await retailer.get_suppliers(
                    access_token=access_token,
                    store_id=store_id,
                    query=supplier_id,
                    limit=5,
                )
                sup_data = sup_res.body.get("data")
                s_list = (
                    sup_data.get("suppliers", [])
                    if isinstance(sup_data, dict)
                    else sup_data
                    if isinstance(sup_data, list)
                    else []
                )
                for s in s_list:
                    if (
                        isinstance(s, dict)
                        and str(s.get("id") or s.get("_id")) == supplier_id
                        and s.get("name")
                    ):
                        supplier_name = str(s["name"]).strip()
                        break
            except Exception:
                pass

        for item in sanitized_items:
            expected_pname = (item.get("productName") or "").strip()
            try:
                prod_res = await retailer.get_products(
                    access_token=access_token,
                    store_id=store_id,
                    query=item["productId"],
                    limit=5,
                )
                p_data = prod_res.body.get("data") or []
                matched = None
                for p in p_data:
                    if (
                        isinstance(p, dict)
                        and str(p.get("id") or p.get("_id")) == item["productId"]
                    ):
                        matched = p
                        break

                if expected_pname:
                    p_name = str(matched.get("name") if matched else "").strip()
                    if (
                        p_name
                        and expected_pname.lower() not in p_name.lower()
                        and p_name.lower() not in expected_pname.lower()
                    ):
                        search_res = await retailer.get_products(
                            access_token=access_token,
                            store_id=store_id,
                            query=expected_pname,
                            limit=5,
                        )
                        s_data = search_res.body.get("data") or []
                        for sp in s_data:
                            if isinstance(sp, dict) and sp.get("name"):
                                sp_name = str(sp["name"]).lower()
                                if (
                                    expected_pname.lower() in sp_name
                                    or sp_name in expected_pname.lower()
                                ):
                                    matched = sp
                                    item["productId"] = str(sp.get("id") or sp.get("_id"))
                                    item["productName"] = sp["name"]
                                    break

                if matched is not None:
                    if not item.get("productName") and matched.get("name"):
                        item["productName"] = matched["name"]
                    if "purchasePrice" not in item:
                        pricing = (
                            matched.get("pricing")
                            if isinstance(matched.get("pricing"), dict)
                            else {}
                        )
                        p_price = (
                            pricing.get("purchasePrice")
                            or pricing.get("sellingPrice")
                            or matched.get("sellingPrice")
                        )
                        if (
                            isinstance(p_price, (int, float))
                            and not isinstance(p_price, bool)
                            and p_price > 0
                        ):
                            item["purchasePrice"] = float(p_price)
                            item["totalPrice"] = round(
                                float(p_price) * item["quantity"], 2
                            )
                            total_amount += item["totalPrice"]
            except Exception:
                pass

    draft_id = f"po_{uuid.uuid4().hex[:8]}"

    args["supplierId"] = supplier_id
    args["supplierName"] = supplier_name
    args["items"] = sanitized_items
    args["storeId"] = store_id

    summary: dict[str, Any] = {
        "action": "create_purchase_order",
        "prompt": "Create purchase order",
        "supplierId": supplier_id,
        "supplierName": supplier_name,
        "itemCount": len(sanitized_items),
        "totalQuantity": total_qty,
        "currency": "INR",
        "items": sanitized_items,
        "paymentTerms": args.get("paymentTerms") or "30_DAYS",
    }
    if total_amount > 0:
        summary["totalAmount"] = round(total_amount, 2)
    if args.get("reference"):
        summary["reference"] = str(args["reference"]).strip()
    if args.get("notes"):
        summary["notes"] = str(args["notes"]).strip()
    if args.get("expectedDeliveryDate"):
        summary["expectedDeliveryDate"] = str(args["expectedDeliveryDate"]).strip()

    record = await store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER,
        draft_id=draft_id,
        summary=summary,
        tool_name=call.name,
        arguments=args,
    )
    _audit_pending(record, audit_trail=audit_trail, metrics=metrics)
    return record
