from __future__ import annotations

from typing import Any

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
        try:
            response = await context.retailer.add_stock(
                access_token=context.access_token,
                store_id=context.store_id,
                product_id=product_id,
                quantity=float(quantity),
                purchase_price=float(purchase_price),
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


SENSITIVE_TOOL_HANDLERS = {
    "release_invoice": release_invoice,
    "ledger_credit": ledger_credit,
    "ledger_debit": ledger_debit,
    "add_stock": add_stock,
}
