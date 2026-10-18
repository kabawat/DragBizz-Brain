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
    hindi = language.lower().startswith("hi")
    status = data.get("billsStatus")
    if status == "no_match":
        return _miss_reply(data, hindi=hindi)
    if status == "ambiguous":
        return _choice_reply(data, hindi=hindi)
    if data.get("matchCount") != 1:
        return None
    if status not in {"ok", "empty", "unavailable"}:
        return None
    items = data.get("items")
    if not isinstance(items, list) or len(items) != 1:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    name = item.get("name") if isinstance(item.get("name"), str) else ""
    name = name.strip() or "customer"
    phone = item.get("phone") if isinstance(item.get("phone"), str) else ""
    phone = phone.strip()
    lines = [f"**{name}**"]
    if phone:
        lines.append(phone)
    lines.append("")
    memo = item.get("memo")
    if isinstance(memo, str) and memo.strip():
        lines.append(f'Saved note: "{memo.strip()}"')
        lines.append("")
    account = item.get("account") if isinstance(item.get("account"), dict) else {}
    due = account.get("totalDue") if isinstance(account, dict) else None
    if isinstance(due, (int, float)) and not isinstance(due, bool):
        if due == 0:
            lines.append(
                "Abhi koi due nahi hai." if hindi else "No dues right now."
            )
        else:
            lines.append(f"Due **{_rupee(due)}**")
        lines.append("")
    status = data.get("billsStatus")
    bills = data.get("bills") if isinstance(data.get("bills"), list) else []
    if status == "empty":
        lines.append(
            "Pichle 10 bills mein koi bill nahi."
            if hindi
            else "No bills in the last 10."
        )
    elif status == "unavailable":
        lines.append(
            "Bills load nahi ho paaye." if hindi else "Bills could not be loaded."
        )
    elif bills:
        rendered: list[str] = []
        for bill in bills:
            if not isinstance(bill, dict):
                continue
            block = _bill_block(bill)
            if block:
                rendered.append(block)
        if rendered:
            lines.append("## Recent bills")
            lines.append("")
            lines.append("\n\n".join(rendered))
    return "\n".join(lines).strip()


def _asked_name(data: dict[str, Any]) -> str:
    query = data.get("query")
    if isinstance(query, str) and query.strip():
        return query.strip()
    return "this name"


def _miss_reply(data: dict[str, Any], *, hindi: bool) -> str:
    name = _asked_name(data)
    if hindi:
        return f"**{name}** naam ka koi customer nahi mila."
    return f"No customer matched **{name}**."


def _choice_reply(data: dict[str, Any], *, hindi: bool) -> str:
    name = _asked_name(data)
    items = data.get("items") if isinstance(data.get("items"), list) else []
    count = data.get("matchCount")
    if not isinstance(count, int) or isinstance(count, bool):
        count = len(items)
    by_email = data.get("matchBy") == "email"
    if by_email:
        if hindi:
            head = (
                f"**{name}** naam se koi customer nahi mila. "
                f"Email se {count} mile. Kaun sa?"
            )
        else:
            head = (
                f"No customer named **{name}**. "
                f"{count} matched by email. Which one?"
            )
        cap = "Search pehle 100 tak hai." if hindi else "Showing the first 100."
    elif hindi:
        head = f"**{name}** se {count} customers mile. Kaun sa?"
        cap = "Search pehle 100 tak hai."
    else:
        head = f"**{name}** matched {count} customers. Which one?"
        cap = "Showing the first 100."
    lines = [head, ""]
    if count >= 100:
        lines.append(cap)
        lines.append("")
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("name") if isinstance(item.get("name"), str) else ""
        label = label.strip() or "customer"
        phone = item.get("phone") if isinstance(item.get("phone"), str) else ""
        phone = phone.strip()
        email = item.get("email") if isinstance(item.get("email"), str) else ""
        email = email.strip()
        bits = [label]
        if phone:
            bits.append(phone)
        if by_email and email:
            bits.append(email)
        lines.append("- " + " · ".join(bits))
    return "\n".join(lines).strip()


def _rupee(value: float | int) -> str:
    shown = int(value) if float(value) == int(value) else value
    return f"₹{shown}"


def _bill_block(bill: dict[str, Any]) -> str:
    head: list[str] = []
    total = bill.get("totalAmount")
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        head.append(f"**{_rupee(total)}**")
    when = bill.get("date")
    if isinstance(when, str) and when.strip():
        head.append(when.strip()[:10])
    rows = [f"- {name}" for name in _item_names(bill.get("items"))]
    number = bill.get("invoiceNumber")
    invoice = number.strip() if isinstance(number, str) else ""
    parts: list[str] = []
    if head:
        parts.append("### " + " · ".join(head))
    if rows:
        parts.append("\n".join(rows))
    if invoice:
        parts.append(invoice)
    return "\n\n".join(parts)


def _item_names(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for line in raw:
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
    return names


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
