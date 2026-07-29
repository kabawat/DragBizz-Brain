"""Helpers to stage invoice-release confirmations without bloating ChatService."""

from __future__ import annotations

from typing import Any

from app.confirmations import (
    CONFIRMATION_TYPE_INVOICE_RELEASE,
    InMemoryConfirmationStore,
    PendingConfirmationRecord,
)
from app.core.exceptions import AppError
from app.schemas.chat import PendingConfirmation
from app.schemas.tool import ToolCall, ToolResult


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


def stage_from_draft_result(
    store: InMemoryConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    result: ToolResult,
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
    return store.create(
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=draft_id,
        summary=build_invoice_summary(result.data),
        tool_name="release_invoice",
        arguments={"storeId": store_id, "invoiceId": draft_id},
    )


def stage_from_sensitive_calls(
    store: InMemoryConfirmationStore,
    *,
    user_id: str,
    store_id: str,
    session_id: str,
    sensitive_calls: list[ToolCall],
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
    return store.create(
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
