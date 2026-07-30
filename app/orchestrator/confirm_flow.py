"""Approve/reject confirmation path for staged sensitive actions."""

from __future__ import annotations

from collections.abc import Callable

from app.confirmations import InMemoryConfirmationStore
from app.executors.tool_executor import ToolExecutor
from app.schemas.chat import ChatResponse, ConfirmRequest
from app.schemas.tool import ToolCall
from app.sessions import SessionStore, SessionTurn

GuardOutputFn = Callable[..., str]


async def handle_confirm(
    body: ConfirmRequest,
    *,
    user_id: str,
    request_id: str,
    store_id: str,
    access_token: str,
    confirmations: InMemoryConfirmationStore,
    sessions: SessionStore,
    executor: ToolExecutor,
    guard_output: GuardOutputFn,
) -> ChatResponse:
    if body.action == "reject":
        record = confirmations.reject(
            body.confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=body.session_id,
            draft_id=body.draft_id,
        )
        message = (
            "Release cancelled. The invoice draft is unchanged — "
            "no stock was deducted. "
            f"[Open invoice](/dashboard/invoices/{record.draft_id})"
        )
        await sessions.append_turn(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            turn=SessionTurn(
                user_text="[confirm:reject]",
                assistant_text=message,
                tool_context=None,
            ),
        )
        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider="confirmation",
            model="",
        )

    record = confirmations.consume(
        body.confirmation_id,
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
        draft_id=body.draft_id,
    )
    tool_call = ToolCall(
        id=f"confirm_{record.confirmation_id[:12]}",
        name=record.tool_name,
        arguments=dict(record.arguments),
    )
    tool_results = await executor.execute_confirmations(
        [tool_call],
        access_token=access_token,
        store_id=store_id,
        session_id=body.session_id,
        user_id=user_id,
        confirmation_id=record.confirmation_id,
    )
    result = tool_results[0] if tool_results else None
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
            message = (
                "Invoice was already released. "
                f"[Open invoice]({open_path})"
            )
        else:
            total = None
            if isinstance(record.summary.get("total"), (int, float)):
                total = record.summary["total"]
            total_bit = f" Total ₹{total}." if total is not None else ""
            message = (
                f"Invoice released successfully.{total_bit} "
                f"[Open invoice]({open_path})"
            )
    else:
        err = ""
        if result is not None and isinstance(result.data, dict):
            err = str(result.data.get("message") or result.data.get("code") or "")
        message = (
            "Could not release the invoice"
            + (f": {err}" if err else ".")
            + " Please try again from Invoices."
        )

    message = guard_output(
        message,
        tool_results=tool_results,
        language="hi-IN",
    )

    await sessions.append_turn(
        session_id=body.session_id,
        user_id=user_id,
        store_id=store_id,
        turn=SessionTurn(
            user_text="[confirm:approve]",
            assistant_text=message,
            tool_context=sessions.compact_tool_context(tool_results),
        ),
    )
    return ChatResponse(
        message=message,
        session_id=body.session_id,
        request_id=request_id,
        user_id=user_id,
        provider="confirmation",
        model="",
        tool_calls=[tool_call],
        tool_results=tool_results,
    )
