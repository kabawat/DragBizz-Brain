"""Deterministic who-is reply from one customer dossier.

Skips the model when search returns a single customer so a repeated
question cannot paraphrase a saved note into a biography.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.executors.tool_executor import ToolExecutor
from app.orchestrator.tool_selector import extract_who_is_query
from app.schemas.tool import ToolCall, ToolResult
from app.tools.projection import project_tool_result


@dataclass(frozen=True)
class FastDossierOutcome:
    message: str
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]


def dossier_reply(data: dict[str, Any], *, language: str) -> str | None:
    if data.get("matchCount") != 1:
        return None
    if data.get("billsStatus") not in {"ok", "empty", "unavailable"}:
        return None
    items = data.get("items")
    if not isinstance(items, list) or len(items) != 1:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    hindi = language.lower().startswith("hi")
    name = item.get("name") if isinstance(item.get("name"), str) else ""
    name = name.strip() or "customer"
    phone = item.get("phone") if isinstance(item.get("phone"), str) else ""
    phone = phone.strip()
    head = f"{name}, {phone}." if phone else f"{name}."
    parts = [head]
    memo = item.get("memo")
    if isinstance(memo, str) and memo.strip():
        parts.append(f'Saved note: "{memo.strip()}".')
    account = item.get("account") if isinstance(item.get("account"), dict) else {}
    due = account.get("totalDue") if isinstance(account, dict) else None
    if isinstance(due, (int, float)) and not isinstance(due, bool):
        if due == 0:
            parts.append("Abhi koi due nahi hai." if hindi else "No dues right now.")
        else:
            shown = int(due) if float(due) == int(due) else due
            parts.append(f"Due ₹{shown}.")
    status = data.get("billsStatus")
    bills = data.get("bills") if isinstance(data.get("bills"), list) else []
    if status == "empty":
        parts.append(
            "Pichle 10 bills mein koi bill nahi."
            if hindi
            else "No bills in the last 10."
        )
    elif status == "unavailable":
        parts.append(
            "Bills load nahi ho paaye." if hindi else "Bills could not be loaded."
        )
    elif bills:
        rendered = [_bill_line(bill) for bill in bills if isinstance(bill, dict)]
        rendered = [line for line in rendered if line]
        if rendered:
            parts.append("Recent bills: " + "; ".join(rendered) + ".")
    return " ".join(parts)


def _bill_line(bill: dict[str, Any]) -> str:
    bits: list[str] = []
    number = bill.get("invoiceNumber")
    if isinstance(number, str) and number.strip():
        bits.append(number.strip())
    when = bill.get("date")
    if isinstance(when, str) and when.strip():
        bits.append(when.strip()[:10])
    total = bill.get("totalAmount")
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        shown = int(total) if float(total) == int(total) else total
        bits.append(f"₹{shown}")
    items = bill.get("items")
    names: list[str] = []
    if isinstance(items, list):
        for line in items:
            if not isinstance(line, dict):
                continue
            name = line.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            qty = line.get("qty")
            if isinstance(qty, (int, float)) and not isinstance(qty, bool):
                qty_shown = int(qty) if float(qty) == int(qty) else qty
                names.append(f"{name.strip()} x{qty_shown}")
            else:
                names.append(name.strip())
    text = " ".join(bits)
    if names:
        text = f"{text} ({', '.join(names)})" if text else ", ".join(names)
    return text


async def try_fast_dossier_turn(
    *,
    question: str,
    language: str,
    store_id: str,
    access_token: str,
    session_id: str,
    user_id: str,
    allowed_names: frozenset[str],
    executor: ToolExecutor,
) -> FastDossierOutcome | None:
    if "customer_dossier" not in allowed_names:
        return None
    query = extract_who_is_query(question)
    if not query:
        return None
    call = ToolCall(
        id=f"auto_dossier_{uuid.uuid4().hex[:10]}",
        name="customer_dossier",
        arguments={"storeId": store_id, "query": query},
    )
    results = await executor.execute_reads(
        [call],
        access_token=access_token,
        store_id=store_id,
        allowed_names=allowed_names,
        session_id=session_id,
        user_id=user_id,
        question=question,
    )
    projected = project_tool_result(results[0])
    if not projected.success or not isinstance(projected.data, dict):
        return None
    message = dossier_reply(projected.data, language=language)
    if message is None:
        return None
    return FastDossierOutcome(
        message=message,
        tool_calls=[call],
        tool_results=[projected],
    )
