"""Auto-stage ledger debit/credit after a single customer resolve.

Models often skip tools or stop after search_customer; when the user
already asked for udhaar/jama with an amount, finish deterministically.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.confirmations import ConfirmationStore, PendingConfirmationRecord
from app.executors.tool_executor import ToolExecutor
from app.observability.audit_trail import AuditTrail
from app.observability.metrics import MetricsRegistry
from app.orchestrator.confirmation import (
    pending_to_schema,
    stage_from_sensitive_calls,
)
from app.orchestrator.tool_selector import user_requested_sensitive_action
from app.schemas.chat import PendingConfirmation
from app.schemas.tool import ToolCall, ToolResult
from app.tools.projection import project_tool_result


def _sensitive_placeholder(
    call: ToolCall, staged: PendingConfirmationRecord | None
) -> ToolResult:
    staged_for_call = staged is not None and staged.tool_name == call.name
    draft_id = (
        staged.draft_id
        if staged_for_call and staged is not None
        else call.arguments.get("invoiceId") or call.arguments.get("customerId")
    )
    confirmation_id = (
        staged.confirmation_id if staged_for_call and staged is not None else None
    )
    data: dict[str, Any] = {
        "status": "pending_confirmation",
        "confirmationId": confirmation_id,
        "draftId": draft_id,
    }
    amount = call.arguments.get("amount")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        data["amount"] = amount
    customer_id = call.arguments.get("customerId")
    if isinstance(customer_id, str) and customer_id.strip():
        data["customerId"] = customer_id.strip()
    return ToolResult(tool=call.name, success=True, data=data)

_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:₹|(?<![a-z])rs\.?|(?<![a-z])inr)[ \t]*([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"|([0-9][0-9,]*(?:\.[0-9]+)?)[ \t]*(?:rupees?|rupaye|rs\b)",
    re.IGNORECASE,
)
_BARE_AMOUNT_RE = re.compile(r"\b([1-9]\d{0,6}(?:\.\d{1,2})?)\b")


def parse_ledger_amount(question: str) -> float | None:
    text = question.strip()
    if not text:
        return None
    match = _CURRENCY_AMOUNT_RE.search(text)
    raw = None
    if match:
        raw = match.group(1) or match.group(2)
    else:
        # Prefer amounts near khata/udhaar/jama words.
        for candidate in _BARE_AMOUNT_RE.finditer(text):
            value = candidate.group(1)
            if len(value) >= 10:
                continue
            start = max(0, candidate.start() - 24)
            end = min(len(text), candidate.end() + 24)
            window = text[start:end].lower()
            if any(
                token in window
                for token in (
                    "udhaar",
                    "udhar",
                    "debit",
                    "jama",
                    "khata",
                    "khate",
                    "add",
                    "daal",
                    "dalo",
                    "payment",
                    "rs",
                    "₹",
                )
            ):
                raw = value
                break
    if raw is None:
        return None
    try:
        amount = float(raw.replace(",", ""))
    except ValueError:
        return None
    if amount <= 0 or amount > 10_000_000:
        return None
    return int(amount) if amount == int(amount) else amount


def _customer_refs(results: list[ToolResult]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for result in results:
        if not result.success or not isinstance(result.data, dict):
            continue
        data = result.data
        if result.tool in {"search_customer"}:
            items = data.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                customer_id = item.get("id")
                if not isinstance(customer_id, str) or not customer_id.strip():
                    continue
                customer_id = customer_id.strip()
                if customer_id in seen:
                    continue
                seen.add(customer_id)
                name = item.get("name")
                label = name.strip() if isinstance(name, str) and name.strip() else "customer"
                refs.append((customer_id, label))
        elif result.tool in {"create_customer", "update_customer"}:
            customer_id = data.get("id")
            nested = data.get("customer")
            if isinstance(nested, dict) and isinstance(nested.get("id"), str):
                customer_id = nested.get("id")
            if not isinstance(customer_id, str) or not customer_id.strip():
                continue
            customer_id = customer_id.strip()
            if customer_id in seen:
                continue
            seen.add(customer_id)
            name = data.get("name")
            if isinstance(nested, dict) and isinstance(nested.get("name"), str):
                name = nested.get("name")
            label = name.strip() if isinstance(name, str) and name.strip() else "customer"
            refs.append((customer_id, label))
    return refs


def maybe_auto_ledger_call(
    *,
    question: str,
    store_id: str,
    allowed_names: frozenset[str],
    results: list[ToolResult],
    already_called: set[str],
) -> ToolCall | None:
    if already_called & {"ledger_debit", "ledger_credit"}:
        return None
    want_debit = (
        "ledger_debit" in allowed_names
        and user_requested_sensitive_action(question, "ledger_debit")
    )
    want_credit = (
        "ledger_credit" in allowed_names
        and user_requested_sensitive_action(question, "ledger_credit")
    )
    if want_debit == want_credit:
        return None
    tool_name = "ledger_debit" if want_debit else "ledger_credit"
    amount = parse_ledger_amount(question)
    if amount is None:
        return None
    refs = _customer_refs(results)
    if len(refs) != 1:
        return None
    customer_id, _name = refs[0]
    return ToolCall(
        id=f"auto_{tool_name}_{uuid.uuid4().hex[:10]}",
        name=tool_name,
        arguments={
            "storeId": store_id,
            "customerId": customer_id,
            "amount": amount,
        },
    )


def ledger_pending_message(
    *,
    tool_name: str,
    amount: float | int,
    customer_name: str,
    language: str,
) -> str:
    rupees = int(amount) if float(amount) == int(amount) else amount
    name = customer_name or "customer"
    lang = language.lower()
    if tool_name == "ledger_credit":
        if lang.startswith("hi"):
            return (
                f"{name} ke khate mein ₹{rupees} jama confirm ke liye ready hai. "
                "App mein Confirm dabao."
            )
        return (
            f"Payment of ₹{rupees} for {name} is ready to confirm. "
            "Tap Confirm in the app."
        )
    if lang.startswith("hi"):
        return (
            f"{name} ke khate mein ₹{rupees} udhaar confirm ke liye ready hai. "
            "App mein Confirm dabao."
        )
    return (
        f"₹{rupees} debit on {name}'s khata is ready to confirm. "
        "Tap Confirm in the app."
    )


def customer_label_for_id(results: list[ToolResult], customer_id: str) -> str:
    for cid, name in _customer_refs(results):
        if cid == customer_id:
            return name
    return "customer"


_BEFORE_KHATA_RE = re.compile(
    r"^(.+?)\s+(?:ke|ki|ka)\s+khat",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"\b([6-9]\d{9})\b")


def extract_customer_query(question: str) -> str | None:
    text = question.strip()
    if not text:
        return None
    phone = _PHONE_RE.search(text)
    if phone:
        return phone.group(1)
    before = _BEFORE_KHATA_RE.match(text)
    if before:
        query = before.group(1).strip(" .,:-")
        return query or None
    return None


def wanted_ledger_tool(
    question: str, allowed_names: frozenset[str]
) -> str | None:
    want_debit = (
        "ledger_debit" in allowed_names
        and user_requested_sensitive_action(question, "ledger_debit")
    )
    want_credit = (
        "ledger_credit" in allowed_names
        and user_requested_sensitive_action(question, "ledger_credit")
    )
    if want_debit == want_credit:
        return None
    return "ledger_debit" if want_debit else "ledger_credit"


@dataclass(frozen=True)
class FastLedgerOutcome:
    message: str
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    pending_confirmation: PendingConfirmation | None


async def try_fast_ledger_turn(
    *,
    question: str,
    language: str,
    store_id: str,
    access_token: str,
    session_id: str,
    user_id: str,
    allowed_names: frozenset[str],
    executor: ToolExecutor,
    confirmations: ConfirmationStore,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
) -> FastLedgerOutcome | None:
    """Search + stage ledger without an LLM when the ask is unambiguous."""
    if "search_customer" not in allowed_names:
        return None
    tool_name = wanted_ledger_tool(question, allowed_names)
    if tool_name is None:
        return None
    amount = parse_ledger_amount(question)
    if amount is None:
        return None
    query = extract_customer_query(question)
    if not query:
        return None

    search_call = ToolCall(
        id=f"auto_search_{uuid.uuid4().hex[:10]}",
        name="search_customer",
        arguments={"storeId": store_id, "query": query},
    )
    search_results = await executor.execute_reads(
        [search_call],
        access_token=access_token,
        store_id=store_id,
        allowed_names=allowed_names,
        session_id=session_id,
        user_id=user_id,
        question=question,
    )
    projected_search = [project_tool_result(item) for item in search_results]
    ledger_call = maybe_auto_ledger_call(
        question=question,
        store_id=store_id,
        allowed_names=allowed_names,
        results=projected_search,
        already_called=set(),
    )
    if ledger_call is None:
        return None

    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id=user_id,
        store_id=store_id,
        session_id=session_id,
        sensitive_calls=[ledger_call],
        audit_trail=audit_trail,
        metrics=metrics,
    )
    projected_ledger = project_tool_result(
        _sensitive_placeholder(ledger_call, staged)
    )
    customer_id = str(ledger_call.arguments.get("customerId") or "")
    message = ledger_pending_message(
        tool_name=tool_name,
        amount=amount,
        customer_name=customer_label_for_id(projected_search, customer_id),
        language=language,
    )
    pending = pending_to_schema(staged) if staged is not None else None
    return FastLedgerOutcome(
        message=message,
        tool_calls=[search_call, ledger_call],
        tool_results=[*projected_search, projected_ledger],
        pending_confirmation=pending,
    )
