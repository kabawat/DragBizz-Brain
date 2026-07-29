from __future__ import annotations

from typing import Any

from app.integrations.retailer_client import RetailerHttpError
from app.schemas.tool import ToolResult
from app.tools.context import ToolContext


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
            store_id=arguments["storeId"],
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


SENSITIVE_TOOL_HANDLERS = {
    "release_invoice": release_invoice,
}
