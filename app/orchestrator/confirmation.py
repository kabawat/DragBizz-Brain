"""Helpers to stage invoice-release confirmations without bloating ChatService."""

from __future__ import annotations

from typing import Any

from app.confirmations import (
    CONFIRMATION_TYPE_INVOICE_RELEASE,
    CONFIRMATION_TYPE_LEDGER_CREDIT,
    CONFIRMATION_TYPE_LEDGER_DEBIT,
    ConfirmationStore,
    PendingConfirmationRecord,
)
from app.core.exceptions import AppError
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
