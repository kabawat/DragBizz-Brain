"""Deterministic who-is reply from one customer dossier.

Skips the model when search returns a single customer so a repeated
question cannot paraphrase a saved note into a biography.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ledger_auto import wanted_ledger_tool
from app.orchestrator.tool_selector import _PURCHASE_RANK_RE, extract_who_is_query
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
    elif hindi:
        head = f"**{name}** naam se {count} customers mile. Kaun sa?"
    else:
        head = f"**{name}** matched {count} customers by name. Which one?"
    lines = [head, ""]
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


_NAME_LIST_RE = re.compile(
    r"\b([1-9]\d?)\s+customers?\b.{0,48}\b(?:names?|naam)\b",
    re.IGNORECASE,
)
_NAME_LIST_MORE_RE = re.compile(
    r"purchase|khareed|saman|samaan|jyada|zyada|kitn|udhari|udhaar|udhar|"
    r"baaki|baqi|\bdue\b|amount|total",
    re.IGNORECASE,
)
_DUE_LIST_RE = re.compile(
    r"\b(?:udhari|udhaar|udhar|baaki|baqi)\b",
    re.IGNORECASE,
)


def name_list_count(question: str) -> int | None:
    text = question.strip()
    if _NAME_LIST_MORE_RE.search(text):
        return None
    match = _NAME_LIST_RE.search(text)
    if match is None:
        return None
    count = int(match.group(1))
    return count if count <= 20 else None


def purchase_rank_count(question: str) -> int | None:
    if _PURCHASE_RANK_RE.search(question.strip()) is None:
        return None
    match = _NAME_LIST_RE.search(question)
    if match is None:
        return 4
    count = int(match.group(1))
    return count if count <= 20 else 20


def _purchase_reply(data: dict[str, Any]) -> str:
    items = data.get("items") if isinstance(data.get("items"), list) else []
    scanned = data.get("billsScanned")
    scanned_n = scanned if isinstance(scanned, int) else 0
    if not items:
        return f"No customer purchases in the last {scanned_n} released bills."
    scope = (
        f"From the latest {scanned_n} released bills."
        if data.get("capped")
        else f"From {scanned_n} released bills."
    )
    lines = ["**Top customers by purchase**", "", scope, ""]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        name = name.strip() or "customer"
        phone = item.get("phone") if isinstance(item.get("phone"), str) else ""
        phone = phone.strip()
        total = item.get("total")
        bits = [name]
        if phone:
            bits.append(phone)
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            shown = int(total) if float(total) == int(total) else total
            bits.append(f"₹{shown}")
        bills = item.get("bills")
        if isinstance(bills, int) and not isinstance(bills, bool):
            bits.append(f"{bills} bills")
        lines.append("- " + " · ".join(bits))
    return "\n".join(lines)


async def try_fast_purchase_rank(
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
    """Top customers by released-bill total. Amounts come from those bills."""
    del language
    if "top_customers" not in allowed_names:
        return None
    count = purchase_rank_count(question)
    if count is None:
        return None
    call = ToolCall(
        id=f"auto_top_{uuid.uuid4().hex[:10]}",
        name="top_customers",
        arguments={"storeId": store_id, "limit": count},
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
    return FastDossierOutcome(
        message=_purchase_reply(projected.data),
        tool_calls=[call],
        tool_results=[projected],
    )


def _name_list_reply(items: list[Any], count: int, *, hindi: bool) -> str:
    shown = items[:count]
    if hindi:
        head = f"**{len(shown)} customer** ke naam:"
    else:
        head = f"**{len(shown)} customer** names:"
    lines = [head, ""]
    for item in shown:
        if not isinstance(item, dict):
            continue
        label = item.get("name") if isinstance(item.get("name"), str) else ""
        label = label.strip() or "customer"
        phone = item.get("phone") if isinstance(item.get("phone"), str) else ""
        phone = phone.strip()
        lines.append(f"- {label} · {phone}" if phone else f"- {label}")
    return "\n".join(lines).strip()


async def try_fast_name_list(
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
    """List customer names only. No dues, so a count cannot fail the amount check."""
    if "search_customer" not in allowed_names:
        return None
    count = name_list_count(question)
    if count is None:
        return None
    call = ToolCall(
        id=f"auto_names_{uuid.uuid4().hex[:10]}",
        name="search_customer",
        arguments={"storeId": store_id, "query": ""},
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
    items = projected.data.get("items")
    if not isinstance(items, list) or not items:
        return None
    message = _name_list_reply(
        items,
        count,
        hindi=language.lower().startswith("hi"),
    )
    return FastDossierOutcome(
        message=message,
        tool_calls=[call],
        tool_results=[projected],
    )


def _due_rows(items: list[Any]) -> list[tuple[float, str, str]]:
    rows: list[tuple[float, str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        due = item.get("totalDue")
        if not isinstance(due, (int, float)) or isinstance(due, bool) or due <= 0:
            continue
        customer = item.get("customer")
        if not isinstance(customer, dict):
            customer = {}
        label = customer.get("name") if isinstance(customer.get("name"), str) else ""
        label = label.strip() or "customer"
        phone = customer.get("phone") if isinstance(customer.get("phone"), str) else ""
        email = customer.get("email") if isinstance(customer.get("email"), str) else ""
        contact = phone.strip() or email.strip()
        rows.append((float(due), label, contact))
    rows.sort(key=lambda row: row[0], reverse=True)
    return rows


def _due_list_reply(items: list[Any]) -> str:
    rows = _due_rows(items)
    if not rows:
        return "Kisi customer par abhi udhari nahi hai."
    lines = ["**Udhari**", ""]
    for due, label, contact in rows:
        shown = int(due) if due == int(due) else due
        bits = [label]
        if contact:
            bits.append(contact)
        bits.append(f"₹{shown}")
        lines.append("- " + " · ".join(bits))
    return "\n".join(lines)


_DUE_LIST_SCOPE_RE = re.compile(
    r"\b(?:list|konsa|kaun|sab|sare|saare|jin)\b",
    re.IGNORECASE,
)


async def try_fast_due_list(
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
    """Store-wide dues with name and phone or email. Skips one-customer writes."""
    del language
    if "list_customer_accounts" not in allowed_names:
        return None
    text = question.strip()
    if _DUE_LIST_RE.search(text) is None or _DUE_LIST_SCOPE_RE.search(text) is None:
        return None
    if wanted_ledger_tool(text, allowed_names) is not None:
        return None
    call = ToolCall(
        id=f"auto_dues_{uuid.uuid4().hex[:10]}",
        name="list_customer_accounts",
        arguments={"storeId": store_id, "hasDue": True, "limit": 20},
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
    items = projected.data.get("items")
    message = _due_list_reply(items if isinstance(items, list) else [])
    return FastDossierOutcome(
        message=message,
        tool_calls=[call],
        tool_results=[projected],
    )


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
