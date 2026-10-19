from __future__ import annotations

from typing import Any

from app.confirmations.categories import normalize_expense_category
from app.core.dates import resolve_expense_date
from app.integrations.retailer_client import RetailerHttpError
from app.schemas.tool import ToolResult
from app.tools.context import ToolContext
from app.tools.ledger_mapping import (
    LEDGER_CREDIT_TYPE,
    LEDGER_DEBIT_TYPE,
    LedgerRetailerType,
)


async def release_invoice(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    """Execute invoice release after explicit user confirmation only."""
    invoice_id = arguments.get("invoiceId")
    if not isinstance(invoice_id, str) or not invoice_id.strip():
        return ToolResult(
            tool="release_invoice",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "invoiceId is required",
            },
        )
    try:
        response = await context.retailer.release_invoice(
            access_token=context.access_token,
            store_id=context.store_id,
            invoice_id=invoice_id.strip(),
            payment_status=arguments.get("paymentStatus"),
            paid_amount=arguments.get("paidAmount"),
            payment_mode=arguments.get("paymentMode"),
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="release_invoice",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )

    data = response.body.get("data")
    payload: dict[str, Any]
    if isinstance(data, dict):
        # Retailer may wrap as { invoice, alreadyReleased } or bare invoice.
        if "invoice" in data and isinstance(data["invoice"], dict):
            payload = dict(data)
        else:
            payload = {"invoice": data}
            if data.get("alreadyReleased") is True:
                payload["alreadyReleased"] = True
        if data.get("alreadyReleased") is True:
            payload["alreadyReleased"] = True
    else:
        payload = {"invoice": data}

    invoice = payload.get("invoice")
    invoice_id_out = None
    if isinstance(invoice, dict):
        for key in ("id", "_id"):
            value = invoice.get(key)
            if isinstance(value, str) and value.strip():
                invoice_id_out = value.strip()
                break
    if invoice_id_out is None:
        invoice_id_out = invoice_id.strip()
    payload["openPath"] = f"/dashboard/invoices/{invoice_id_out}"
    return ToolResult(tool="release_invoice", success=True, data=payload)


async def ledger_credit(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    return await _ledger_write(
        "ledger_credit",
        LEDGER_CREDIT_TYPE,
        arguments,
        context,
    )


async def ledger_debit(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    return await _ledger_write(
        "ledger_debit",
        LEDGER_DEBIT_TYPE,
        arguments,
        context,
    )


async def add_stock(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    raw_items = arguments.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return ToolResult(
            tool="add_stock",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "items must be a non-empty array",
            },
        )

    added: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            return ToolResult(
                tool="add_stock",
                success=False,
                data={
                    "code": "TOOL_ARGS_INVALID",
                    "message": "each item must be an object",
                },
            )
        product_id = raw.get("productId")
        if not isinstance(product_id, str) or not product_id.strip():
            return ToolResult(
                tool="add_stock",
                success=False,
                data={
                    "code": "TOOL_ARGS_INVALID",
                    "message": "productId is required on each item",
                },
            )
        quantity = raw.get("quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, (int, float))
            or quantity <= 0
        ):
            return ToolResult(
                tool="add_stock",
                success=False,
                data={
                    "code": "TOOL_ARGS_INVALID",
                    "message": "quantity must be > 0 on each item",
                },
            )
        purchase_price = raw.get("purchasePrice")
        if (
            isinstance(purchase_price, bool)
            or not isinstance(purchase_price, (int, float))
            or purchase_price <= 0
        ):
            purchase_price = 1.0
        product_id = product_id.strip()
        idempotency_key = arguments.get("idempotencyKey")
        try:
            response = await context.retailer.add_stock(
                access_token=context.access_token,
                store_id=context.store_id,
                product_id=product_id,
                quantity=float(quantity),
                purchase_price=float(purchase_price),
                idempotency_key=str(idempotency_key).strip()
                if isinstance(idempotency_key, str) and idempotency_key.strip()
                else None,
            )
        except RetailerHttpError as exc:
            return ToolResult(
                tool="add_stock",
                success=False,
                data={"code": exc.code, "message": exc.message},
            )
        data = response.body.get("data")
        row: dict[str, Any] = {
            "productId": product_id,
            "quantity": float(quantity),
        }
        if isinstance(raw.get("productName"), str) and raw["productName"].strip():
            row["productName"] = raw["productName"].strip()
        if isinstance(raw.get("sourceName"), str) and raw["sourceName"].strip():
            row["sourceName"] = raw["sourceName"].strip()
        current = raw.get("currentStock")
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            row["currentStock"] = float(current)
            row["finalStock"] = float(current) + float(quantity)
        if isinstance(data, dict):
            if data.get("batchNo") is not None:
                row["batchNo"] = data.get("batchNo")
            if data.get("id") is not None:
                row["inventoryId"] = str(data.get("id"))
        added.append(row)

    return ToolResult(
        tool="add_stock",
        success=True,
        data={"items": added, "count": len(added)},
    )


async def _ledger_write(
    tool: str,
    transaction_type: LedgerRetailerType,
    arguments: dict[str, Any],
    context: ToolContext,
) -> ToolResult:
    idempotency_key = arguments.get("idempotencyKey")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return ToolResult(
            tool=tool,
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "idempotencyKey is required for ledger writes",
            },
        )
    try:
        response = await context.retailer.create_ledger_transaction(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=arguments["customerId"],
            transaction_type=transaction_type,
            amount=float(arguments["amount"]),
            idempotency_key=idempotency_key.strip(),
            notes=arguments.get("notes"),
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool=tool,
            success=False,
            data={"code": exc.code, "message": exc.message},
        )

    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"transaction": data}
    # Keep the confirmed amount on the result so the reply can quote it.
    payload = {**payload, "amount": float(arguments["amount"])}
    return ToolResult(tool=tool, success=True, data=payload)


async def merge_customers(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    primary_id = arguments.get("primaryId")
    duplicate_id = arguments.get("duplicateId")
    if not isinstance(primary_id, str) or not primary_id.strip():
        return ToolResult(
            tool="merge_customers",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "primaryId is required",
            },
        )
    if not isinstance(duplicate_id, str) or not duplicate_id.strip():
        return ToolResult(
            tool="merge_customers",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "duplicateId is required",
            },
        )
    primary_id = primary_id.strip()
    duplicate_id = duplicate_id.strip()
    if primary_id == duplicate_id:
        return ToolResult(
            tool="merge_customers",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "primaryId and duplicateId must differ",
            },
        )
    try:
        response = await context.retailer.merge_customers(
            access_token=context.access_token,
            store_id=context.store_id,
            primary_id=primary_id,
            duplicate_id=duplicate_id,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="merge_customers",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"raw": data}
    payload = {
        **payload,
        "primaryId": primary_id,
        "duplicateId": duplicate_id,
        "openPath": f"/dashboard/customers/{primary_id}",
    }
    return ToolResult(tool="merge_customers", success=True, data=payload)


async def set_opening_balance(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    if not isinstance(customer_id, str) or not customer_id.strip():
        return ToolResult(
            tool="set_opening_balance",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "customerId is required",
            },
        )
    try:
        response = await context.retailer.create_customer_account(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip(),
            total_due=_optional_non_negative(arguments.get("totalDue")),
            total_paid=_optional_non_negative(arguments.get("totalPaid")),
            total_amount=_optional_non_negative(arguments.get("totalAmount")),
            notes=arguments.get("notes")
            if isinstance(arguments.get("notes"), str)
            else None,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="set_opening_balance",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"account": data}
    payload = {
        **payload,
        "customerId": customer_id.strip(),
        "openPath": f"/dashboard/customers/{customer_id.strip()}",
    }
    return ToolResult(tool="set_opening_balance", success=True, data=payload)


async def record_customer_payment(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    payment_type = arguments.get("paymentType")
    payment = arguments.get("payment")
    if not isinstance(customer_id, str) or not customer_id.strip():
        return ToolResult(
            tool="record_customer_payment",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "customerId is required",
            },
        )
    if not isinstance(payment_type, str) or not payment_type.strip():
        return ToolResult(
            tool="record_customer_payment",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "paymentType is required",
            },
        )
    if not isinstance(payment, list) or not payment:
        return ToolResult(
            tool="record_customer_payment",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "payment must be a non-empty array",
            },
        )
    idempotency_key = arguments.get("idempotencyKey")
    try:
        response = await context.retailer.create_customer_payment(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip(),
            payment_type=payment_type.strip().upper(),
            payment=list(payment),
            invoice=arguments.get("invoiceId")
            if isinstance(arguments.get("invoiceId"), str)
            else None,
            invoice_allocations=arguments.get("invoiceAllocations")
            if isinstance(arguments.get("invoiceAllocations"), list)
            else None,
            notes=arguments.get("notes")
            if isinstance(arguments.get("notes"), str)
            else None,
            idempotency_key=idempotency_key.strip()
            if isinstance(idempotency_key, str) and idempotency_key.strip()
            else None,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="record_customer_payment",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"payment": data}
    total = sum(
        float(row["amount"])
        for row in payment
        if isinstance(row, dict)
        and isinstance(row.get("amount"), (int, float))
        and not isinstance(row.get("amount"), bool)
    )
    payload = {
        **payload,
        "customerId": customer_id.strip(),
        "amount": total,
        "openPath": f"/dashboard/customers/{customer_id.strip()}",
    }
    return ToolResult(
        tool="record_customer_payment", success=True, data=payload
    )


async def update_customer_payment(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    payment_id = arguments.get("paymentId")
    notes = arguments.get("notes")
    if not isinstance(payment_id, str) or not payment_id.strip():
        return ToolResult(
            tool="update_customer_payment",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "paymentId is required",
            },
        )
    if not isinstance(notes, str):
        return ToolResult(
            tool="update_customer_payment",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "notes is required",
            },
        )
    try:
        response = await context.retailer.update_customer_payment(
            access_token=context.access_token,
            store_id=context.store_id,
            payment_id=payment_id.strip(),
            notes=notes,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="update_customer_payment",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"payment": data}
    return ToolResult(
        tool="update_customer_payment", success=True, data=payload
    )


async def create_collect_link(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    if not isinstance(customer_id, str) or not customer_id.strip():
        return ToolResult(
            tool="create_collect_link",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "customerId is required",
            },
        )
    amount = arguments.get("amount")
    amount_val: float | None = None
    if amount is not None:
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or amount <= 0
        ):
            return ToolResult(
                tool="create_collect_link",
                success=False,
                data={
                    "code": "TOOL_ARGS_INVALID",
                    "message": "amount must be greater than 0",
                },
            )
        amount_val = float(amount)
    try:
        response = await context.retailer.create_collect_link(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip(),
            amount=amount_val,
            notes=arguments.get("notes")
            if isinstance(arguments.get("notes"), str)
            else None,
            description=arguments.get("description")
            if isinstance(arguments.get("description"), str)
            else None,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="create_collect_link",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"collectLink": data}
    payload = {
        **payload,
        "customerId": customer_id.strip(),
        "openPath": f"/dashboard/customers/{customer_id.strip()}",
    }
    if amount_val is not None:
        payload["amount"] = amount_val
    return ToolResult(tool="create_collect_link", success=True, data=payload)


async def send_payment_reminder(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    if not isinstance(customer_id, str) or not customer_id.strip():
        return ToolResult(
            tool="send_payment_reminder",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "customerId is required",
            },
        )
    channel = arguments.get("channel")
    try:
        response = await context.retailer.create_payment_reminder(
            access_token=context.access_token,
            store_id=context.store_id,
            customer_id=customer_id.strip(),
            channel=channel.strip().upper()
            if isinstance(channel, str) and channel.strip()
            else None,
            include_payment_link=arguments.get("includePaymentLink")
            if isinstance(arguments.get("includePaymentLink"), bool)
            else None,
            notes=arguments.get("notes")
            if isinstance(arguments.get("notes"), str)
            else None,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="send_payment_reminder",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"reminder": data}
    payload = {
        **payload,
        "customerId": customer_id.strip(),
        "openPath": f"/dashboard/customers/{customer_id.strip()}",
    }
    return ToolResult(
        tool="send_payment_reminder", success=True, data=payload
    )


def _optional_non_negative(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return float(value)


async def create_expense(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    title = arguments.get("title")
    if not isinstance(title, str) or not title.strip():
        return ToolResult(
            tool="create_expense",
            success=False,
            data={"code": "TOOL_ARGS_INVALID", "message": "title is required"},
        )
    amount = arguments.get("amount")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or amount <= 0
    ):
        return ToolResult(
            tool="create_expense",
            success=False,
            data={"code": "TOOL_ARGS_INVALID", "message": "amount must be > 0"},
        )
    category_key, _ = normalize_expense_category(
        arguments.get("category"), title=title.strip()
    )
    context_text = f"{context.question} {title.strip()}".strip()
    resolved_date = resolve_expense_date(
        arguments.get("date"), context_text=context_text
    )

    desc = (
        arguments.get("description")
        if isinstance(arguments.get("description"), str)
        else arguments.get("notes")
        if isinstance(arguments.get("notes"), str)
        else None
    )

    raw_status = arguments.get("status")
    status_val = (
        raw_status.strip().upper()
        if isinstance(raw_status, str) and raw_status.strip()
        else None
    )

    idempotency_key = arguments.get("idempotencyKey")
    try:
        response = await context.retailer.create_expense(
            access_token=context.access_token,
            store_id=context.store_id,
            title=title.strip(),
            amount=float(amount),
            category=category_key,
            date=resolved_date,
            payment_mode=arguments.get("paymentMode")
            if isinstance(arguments.get("paymentMode"), str)
            else None,
            notes=desc,
            description=desc,
            status=status_val,
            idempotency_key=str(idempotency_key).strip()
            if isinstance(idempotency_key, str) and idempotency_key.strip()
            else None,
        )
    except RetailerHttpError as exc:
        return ToolResult(
            tool="create_expense",
            success=False,
            data={"code": exc.code, "message": exc.message},
        )
    data = response.body.get("data") if isinstance(response.body, dict) else {}
    payload = data if isinstance(data, dict) else {}
    expense_id = payload.get("id") or payload.get("_id") or ""
    return ToolResult(
        tool="create_expense",
        success=True,
        data={
            "id": expense_id,
            "title": title.strip(),
            "amount": float(amount),
            "category": category_key,
            "date": resolved_date,
            "openPath": "/dashboard/expenses",
        },
    )


SENSITIVE_TOOL_HANDLERS = {
    "release_invoice": release_invoice,
    "ledger_credit": ledger_credit,
    "ledger_debit": ledger_debit,
    "add_stock": add_stock,
    "merge_customers": merge_customers,
    "set_opening_balance": set_opening_balance,
    "record_customer_payment": record_customer_payment,
    "update_customer_payment": update_customer_payment,
    "create_collect_link": create_collect_link,
    "send_payment_reminder": send_payment_reminder,
    "create_expense": create_expense,
}

