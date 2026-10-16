"""Helpers to stage invoice-release confirmations without bloating ChatService."""

from __future__ import annotations

from typing import Any

from app.confirmations import (
    CONFIRMATION_TYPE_ADD_STOCK,
    CONFIRMATION_TYPE_CREATE_COLLECT_LINK,
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
)

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
from app.core.exceptions import AppError
from app.integrations.retailer_client import RetailerClient, RetailerHttpError
from app.observability.audit_trail import AuditTrail
from app.observability.confirmation_audit import audit_confirmation
from app.observability.metrics import MetricsRegistry
from app.schemas.chat import PendingConfirmation
from app.schemas.tool import ToolCall, ToolResult


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
                **(
                    {"sourceName": item["sourceName"]}
                    if "sourceName" in item
                    else {}
                ),
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
