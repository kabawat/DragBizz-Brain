"""Approve/reject confirmation path for staged sensitive actions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.confirmations import (
    CONFIRMATION_TYPE_LEDGER_CREDIT,
    CONFIRMATION_TYPE_LEDGER_DEBIT,
    ConfirmationStore,
    PendingConfirmationRecord,
)
from app.executors.tool_executor import ToolExecutor
from app.observability.audit_trail import AuditTrail
from app.observability.confirmation_audit import audit_confirmation
from app.observability.metrics import MetricsRegistry
from app.schemas.chat import ChatResponse, ConfirmRequest
from app.schemas.tool import ToolCall, ToolResult
from app.sessions import (
    DurableHistoryStore,
    SessionStore,
    SessionTurn,
    persist_turn_safe,
)
from app.tools.projection import project_tool_results

GuardOutputFn = Callable[..., str]

_AMBIGUOUS_CODES = frozenset({"RETAILER_TIMEOUT", "RETAILER_UNAVAILABLE"})


async def _append_and_persist(
    *,
    sessions: SessionStore,
    history: DurableHistoryStore | None,
    session_id: str,
    user_id: str,
    store_id: str,
    user_text: str,
    assistant_text: str,
    tool_results: list[ToolResult] | None = None,
) -> None:
    await sessions.append_turn(
        session_id=session_id,
        user_id=user_id,
        store_id=store_id,
        turn=SessionTurn(
            user_text=user_text,
            assistant_text=assistant_text,
            tool_context=sessions.compact_tool_context(tool_results or []),
        ),
    )
    await persist_turn_safe(
        history,
        session_id=session_id,
        user_id=user_id,
        store_id=store_id,
        user_text=user_text,
        assistant_text=assistant_text,
        tool_results=tool_results,
    )


async def handle_confirm(
    body: ConfirmRequest,
    *,
    user_id: str,
    request_id: str,
    store_id: str,
    access_token: str,
    confirmations: ConfirmationStore,
    sessions: SessionStore,
    executor: ToolExecutor,
    guard_output: GuardOutputFn,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
    history: DurableHistoryStore | None = None,
) -> ChatResponse:
    if body.action == "reject":
        record = await confirmations.reject(
            body.confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=body.session_id,
            draft_id=body.draft_id,
        )
        audit_confirmation(
            audit_trail=audit_trail,
            metrics=metrics,
            confirmation_id=record.confirmation_id,
            type=record.type,
            status="REJECTED",
            previous_status="PENDING",
            user_id=user_id,
            store_id=store_id,
            session_id=body.session_id,
            tool=record.tool_name,
            business_idempotency_key=record.business_idempotency_key,
        )
        message = _reject_message(record)
        await _append_and_persist(
            sessions=sessions,
            history=history,
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            user_text="[confirm:reject]",
            assistant_text=message,
        )
        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider="confirmation",
            model="",
        )

    prior = await confirmations.get(
        body.confirmation_id,
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
    )
    previous = prior.status
    record = await confirmations.claim(
        body.confirmation_id,
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
        draft_id=body.draft_id,
    )
    audit_confirmation(
        audit_trail=audit_trail,
        metrics=metrics,
        confirmation_id=record.confirmation_id,
        type=record.type,
        status="EXECUTING",
        previous_status=previous,
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
        tool=record.tool_name,
        business_idempotency_key=record.business_idempotency_key,
    )
    tool_call = ToolCall(
        id=f"confirm_{record.confirmation_id[:12]}",
        name=record.tool_name,
        arguments=dict(record.arguments),
    )
    confirm_task = asyncio.create_task(
        executor.execute_confirmations(
            [tool_call],
            access_token=access_token,
            store_id=store_id,
            session_id=body.session_id,
            user_id=user_id,
            confirmation_id=record.confirmation_id,
            business_idempotency_key=record.business_idempotency_key,
        )
    )
    try:
        tool_results = await asyncio.shield(confirm_task)
    except asyncio.CancelledError:
        if confirm_task.done() and not confirm_task.cancelled():
            exc = confirm_task.exception()
            tool_results = confirm_task.result() if exc is None else None
        else:
            tool_results = None
        if tool_results is None:
            await confirmations.complete(
                record.confirmation_id, status="UNKNOWN"
            )
            audit_confirmation(
                audit_trail=audit_trail,
                metrics=metrics,
                confirmation_id=record.confirmation_id,
                type=record.type,
                status="UNKNOWN",
                previous_status="EXECUTING",
                user_id=user_id,
                store_id=store_id,
                session_id=body.session_id,
                tool=record.tool_name,
                business_idempotency_key=record.business_idempotency_key,
            )
            message = _unknown_message(record)
            await _append_and_persist(
                sessions=sessions,
                history=history,
                session_id=body.session_id,
                user_id=user_id,
                store_id=store_id,
                user_text="[confirm:approve]",
                assistant_text=message,
            )
            return ChatResponse(
                message=message,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="confirmation",
                model="",
                tool_calls=[tool_call],
            )
    except Exception:
        await confirmations.complete(
            record.confirmation_id, status="UNKNOWN"
        )
        audit_confirmation(
            audit_trail=audit_trail,
            metrics=metrics,
            confirmation_id=record.confirmation_id,
            type=record.type,
            status="UNKNOWN",
            previous_status="EXECUTING",
            user_id=user_id,
            store_id=store_id,
            session_id=body.session_id,
            tool=record.tool_name,
            business_idempotency_key=record.business_idempotency_key,
        )
        message = _unknown_message(record)
        await _append_and_persist(
            sessions=sessions,
            history=history,
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            user_text="[confirm:approve]",
            assistant_text=message,
        )
        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider="confirmation",
            model="",
            tool_calls=[tool_call],
        )

    projected = project_tool_results(tool_results)
    result = projected[0] if projected else None

    if result is not None and result.success:
        terminal = "SUCCEEDED"
        await confirmations.complete(
            record.confirmation_id, status="SUCCEEDED"
        )
        message = _approve_message(record, result)
    elif _is_ambiguous_failure(result):
        terminal = "UNKNOWN"
        await confirmations.complete(
            record.confirmation_id, status="UNKNOWN"
        )
        message = _unknown_message(record)
    else:
        terminal = "FAILED"
        await confirmations.complete(record.confirmation_id, status="FAILED")
        message = _approve_message(record, result)

    audit_confirmation(
        audit_trail=audit_trail,
        metrics=metrics,
        confirmation_id=record.confirmation_id,
        type=record.type,
        status=terminal,
        previous_status="EXECUTING",
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
        tool=record.tool_name,
        business_idempotency_key=record.business_idempotency_key,
    )

    message = guard_output(
        message,
        tool_results=projected,
        language="hi-IN",
    )

    await _append_and_persist(
        sessions=sessions,
        history=history,
        session_id=body.session_id,
        user_id=user_id,
        store_id=store_id,
        user_text="[confirm:approve]",
        assistant_text=message,
        tool_results=projected,
    )
    return ChatResponse(
        message=message,
        session_id=body.session_id,
        request_id=request_id,
        user_id=user_id,
        provider="confirmation",
        model="",
        tool_calls=[tool_call],
        tool_results=projected,
    )


_LEDGER_TYPES = frozenset(
    {CONFIRMATION_TYPE_LEDGER_CREDIT, CONFIRMATION_TYPE_LEDGER_DEBIT}
)


def _is_ambiguous_failure(result: ToolResult | None) -> bool:
    if result is None or result.success:
        return False
    if not isinstance(result.data, dict):
        return False
    code = str(result.data.get("code") or "")
    if code in _AMBIGUOUS_CODES:
        return True
    message = str(result.data.get("message") or "").lower()
    return "timed out" in message


def _unknown_message(record: PendingConfirmationRecord) -> str:
    if record.type in _LEDGER_TYPES:
        return (
            "The khata write may or may not have completed — status is unclear. "
            "Check the customer ledger before retrying. "
            "If you retry, the same confirmation will reuse the same business key."
        )
    return (
        "Invoice release status is unclear — it may or may not have completed. "
        "Check the invoice in Invoices before retrying. "
        f"[Open invoice](/dashboard/invoices/{record.draft_id})"
    )


def _reject_message(record: PendingConfirmationRecord) -> str:
    if record.type in _LEDGER_TYPES:
        return (
            "Khata entry cancelled. Nothing was written to the customer ledger."
        )
    return (
        "Release cancelled. The invoice draft is unchanged — "
        "no stock was deducted. "
        f"[Open invoice](/dashboard/invoices/{record.draft_id})"
    )


def _money(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _format_inr(value: object) -> str | None:
    amount = _money(value)
    if amount is None:
        return None
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _result_error(result: ToolResult | None) -> str:
    if result is None or not isinstance(result.data, dict):
        return ""
    return str(result.data.get("message") or result.data.get("code") or "")


def _approve_message(
    record: PendingConfirmationRecord, result: ToolResult | None
) -> str:
    if record.type in _LEDGER_TYPES:
        if result is not None and result.success:
            total = _format_inr(record.summary.get("total"))
            label = (
                "Payment"
                if record.type == CONFIRMATION_TYPE_LEDGER_CREDIT
                else "Debit"
            )
            amount = f" of ₹{total}" if total is not None else ""
            return f"{label}{amount} recorded on the customer khata."
        err = _result_error(result)
        return (
            "Could not record the khata entry"
            + (f": {err}" if err else ".")
            + " Nothing was written."
        )

    if result is not None and result.success:
        open_path = None
        if isinstance(result.data, dict):
            open_path = result.data.get("openPath")
        if not isinstance(open_path, str) or not open_path.strip():
            open_path = f"/dashboard/invoices/{record.draft_id}"
        already = (
            isinstance(result.data, dict)
            and result.data.get("alreadyReleased") is True
        )
        if already:
            return f"Invoice was already released. [Open invoice]({open_path})"
        total = _format_inr(record.summary.get("total"))
        total_bit = f" Total ₹{total}." if total is not None else ""
        return (
            f"Invoice released successfully.{total_bit} "
            f"[Open invoice]({open_path})"
        )

    err = _result_error(result)
    return (
        "Could not release the invoice"
        + (f": {err}" if err else ".")
        + " Please try again from Invoices."
    )
