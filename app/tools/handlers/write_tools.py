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


async def create_customer(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    missing = _require_phone_or_email("create_customer", arguments)
    if missing is not None:
        return missing
    try:
        response = await context.retailer.create_customer(
            access_token=context.access_token,
            store_id=arguments["storeId"],
            name=arguments["name"],
            phone=arguments.get("phone"),
            email=arguments.get("email"),
        )
    except RetailerHttpError as exc:
        # Retailer's 409 ("already exists") does not include the existing
        # customer id, and without an id the LLM tends to fall back to a
        # walk-in invoice. Recover deterministically: look the customer up
        # by phone/email and return them as a success.
        if exc.status_code == 409:
            existing = await _find_existing_customer(arguments, context)
            if existing is not None:
                return ToolResult(
                    tool="create_customer",
                    success=True,
                    data=_attach_customer_open_path(
                        {
                            "customer": existing,
                            "existing": True,
                            "message": (
                                "Customer already exists — use this "
                                "customer id, do not create a walk-in "
                                "invoice"
                            ),
                        }
                    ),
                )
        return _failure("create_customer", exc)

    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"raw": data}
    return ToolResult(
        tool="create_customer",
        success=True,
        data=_attach_customer_open_path(payload),
    )


async def _find_existing_customer(
    arguments: dict[str, Any], context: ToolContext
) -> dict[str, Any] | None:
    for key in ("phone", "email"):
        raw = arguments.get(key)
        identifier = raw.strip() if isinstance(raw, str) else ""
        if not identifier:
            continue
        try:
            response = await context.retailer.get_customers(
                access_token=context.access_token,
                store_id=arguments["storeId"],
                query=identifier,
            )
        except RetailerHttpError:
            continue
        items = response.body.get("data") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get(key)
            if isinstance(value, str) and value.strip() == identifier:
                # Contract: GET /customer serializes _id as `id`.
                customer_id = item.get("id")
                if not isinstance(customer_id, str) or not customer_id:
                    continue
                return {
                    "id": customer_id,
                    "name": item.get("name"),
                    "phone": item.get("phone"),
                    "email": item.get("email"),
                }
    return None


async def update_customer(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    missing = _require_phone_or_email("update_customer", arguments)
    if missing is not None:
        return missing
    try:
        response = await context.retailer.update_customer(
            access_token=context.access_token,
            store_id=arguments["storeId"],
            customer_id=arguments["customerId"],
            name=arguments["name"],
            phone=arguments.get("phone"),
            email=arguments.get("email"),
        )
    except RetailerHttpError as exc:
        return _failure("update_customer", exc)

    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"raw": data}
    # Prefer id from body; fall back to the id we just updated.
    if "customer" not in payload and isinstance(arguments.get("customerId"), str):
        payload = {
            **payload,
            "customer": {"id": arguments["customerId"]},
        }
    return ToolResult(
        tool="update_customer",
        success=True,
        data=_attach_customer_open_path(payload),
    )


async def create_invoice_draft(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    try:
        response = await context.retailer.create_invoice_draft(
            access_token=context.access_token,
            store_id=arguments["storeId"],
            items=list(arguments["items"]),
            customer_id=customer_id,
            is_walkin=customer_id is None,
        )
    except RetailerHttpError as exc:
        return _failure("create_invoice_draft", exc)

    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"invoice": data}
    return ToolResult(
        tool="create_invoice_draft",
        success=True,
        data=_attach_invoice_open_path(payload),
    )


async def update_invoice_draft(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    customer_id = arguments.get("customerId")
    items = arguments.get("items")
    if customer_id is None and items is None:
        return ToolResult(
            tool="update_invoice_draft",
            success=False,
            data={
                "code": "TOOL_ARGS_INVALID",
                "message": "Provide customerId and/or items to update",
            },
        )
    try:
        response = await context.retailer.update_invoice_draft(
            access_token=context.access_token,
            store_id=arguments["storeId"],
            invoice_id=arguments["invoiceId"],
            customer_id=customer_id,
            items=list(items) if items is not None else None,
        )
    except RetailerHttpError as exc:
        return _failure("update_invoice_draft", exc)

    data = response.body.get("data")
    payload = data if isinstance(data, dict) else {"invoice": data}
    return ToolResult(
        tool="update_invoice_draft",
        success=True,
        data=_attach_invoice_open_path(payload),
    )


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
            store_id=arguments["storeId"],
            customer_id=arguments["customerId"],
            transaction_type=transaction_type,
            amount=float(arguments["amount"]),
            idempotency_key=idempotency_key.strip(),
            notes=arguments.get("notes"),
        )
    except RetailerHttpError as exc:
        return _failure(tool, exc)

    data = response.body.get("data")
    return ToolResult(
        tool=tool,
        success=True,
        data=data if isinstance(data, dict) else {"transaction": data},
    )


def _require_phone_or_email(
    tool: str, arguments: dict[str, Any]
) -> ToolResult | None:
    phone = arguments.get("phone")
    email = arguments.get("email")
    has_phone = isinstance(phone, str) and bool(phone.strip())
    has_email = isinstance(email, str) and bool(email.strip())
    if has_phone or has_email:
        return None
    return ToolResult(
        tool=tool,
        success=False,
        data={
            "code": "TOOL_ARGS_INVALID",
            "message": "Either phone or email is required",
        },
    )


def _entity_id(entity: Any) -> str | None:
    # Verified contracts differ: serialized responses expose `id`
    # (invoiceSerializer, customerSerializer); invoice update returns
    # the raw document with `_id`. Both keys are real, not speculative.
    if not isinstance(entity, dict):
        return None
    for key in ("id", "_id"):
        value = entity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _attach_customer_open_path(payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = _entity_id(payload.get("customer")) or _entity_id(payload)
    if customer_id is None:
        return payload
    return {
        **payload,
        "openPath": f"/dashboard/customers/{customer_id}",
    }


def _attach_invoice_open_path(payload: dict[str, Any]) -> dict[str, Any]:
    invoice_id = _entity_id(payload.get("invoice")) or _entity_id(payload)
    if invoice_id is None:
        return payload
    return {
        **payload,
        "openPath": f"/dashboard/invoices/{invoice_id}",
    }


def _failure(tool: str, exc: RetailerHttpError) -> ToolResult:
    return ToolResult(
        tool=tool,
        success=False,
        data={"code": exc.code, "message": exc.message},
    )


WRITE_TOOL_HANDLERS = {
    "create_customer": create_customer,
    "update_customer": update_customer,
    "create_invoice_draft": create_invoice_draft,
    "update_invoice_draft": update_invoice_draft,
    "ledger_credit": ledger_credit,
    "ledger_debit": ledger_debit,
}
