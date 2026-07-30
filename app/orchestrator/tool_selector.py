"""Turn intent: routing label + tool subset for the first LLM call.

Routing labels match ``tests/eval/routing_cases.json``:
``tools`` / ``docs`` / ``both`` / ``neither``. Unmatched questions are
``unknown`` (fail open: all tools, full prompt safety rules).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

RoutingLabel = Literal["tools", "docs", "both", "neither", "unknown"]

# Prefer specific live/action families over how-to/neither. Union when
# several families match (e.g. sale + payment in one question).
_FAMILY_TOOLS: dict[str, frozenset[str]] = {
    "sale": frozenset({"today_sale"}),
    "stock": frozenset({"stock_summary", "search_product"}),
    "product": frozenset({"search_product"}),
    "payment": frozenset({"payment_history", "search_customer"}),
    "customer": frozenset(
        {
            "search_customer",
            "create_customer",
            "update_customer",
            "ledger_credit",
            "ledger_debit",
            "payment_history",
        }
    ),
    "invoice": frozenset(
        {
            "search_customer",
            "search_product",
            "create_customer",
            "create_invoice_draft",
            "update_invoice_draft",
            "release_invoice",
        }
    ),
}

_FAMILY_CUES: dict[str, tuple[str, ...]] = {
    "sale": (
        "aaj ki sale",
        "today's sale",
        "today sale",
        "sale kitni",
        "sale kitna",
        "sale batao",
        "kitne bill",
        "bill bane",
        "bills today",
        "today's bills",
    ),
    "stock": (
        "stock me",
        "stock mein",
        "out of stock",
        "stock kitna",
        "stock kitne",
        "stock bacha",
        "stock summary",
        "low stock",
    ),
    "product": (
        "current price",
        "price kya",
        "price batao",
        "product search",
        "sku",
    ),
    "payment": (
        "payments",
        "payment history",
        "payment dikhao",
        "recent payment",
    ),
    "customer": (
        "naya customer",
        "customer banao",
        "customer bana",
        "create customer",
        "add customer",
        "update customer",
        "customer update",
        "ledger credit",
        "ledger debit",
        "udhaar add",
        "udhaar dalo",
        "jama karo",
        "payment record",
    ),
    "invoice": (
        "bill banao",
        "bill bana",
        "invoice banao",
        "invoice bana",
        "create invoice",
        "create bill",
        "make a bill",
        "make bill",
        "make an invoice",
        "make invoice",
        "draft invoice",
        "invoice draft",
        "release invoice",
        "release the draft",
        "release draft",
        "bill for",
        "ke liye bill",
        "ke liye invoice",
    ),
}

# Docs/FAQ path when no tool family matched (aligns with routing_cases docs/*).
_HOW_TO_CUES = (
    "kaise",
    "kaisein",
    "karein",
    "karu",
    "how to",
    "how do i",
    "how do we",
    "steps",
    "guide",
)

# Whole-message small talk (routing_cases neither/*).
_NEITHER_RE = re.compile(
    r"^(hi|hello|hey|yo|thanks|thank you(?:\s+bhai)?|theek hai|"
    r"ok|okay|kem cho|namaste|bye|good morning|good evening)\W*$",
    re.IGNORECASE,
)

_FAMILY_RES = {
    name: re.compile(
        "|".join(re.escape(cue) for cue in cues),
        re.IGNORECASE,
    )
    for name, cues in _FAMILY_CUES.items()
}
_HOW_TO_RE = re.compile(
    "|".join(re.escape(cue) for cue in _HOW_TO_CUES),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TurnIntent:
    routing: RoutingLabel
    tool_names: frozenset[str]


def resolve_turn_intent(
    question: str,
    *,
    available: Iterable[str],
) -> TurnIntent:
    """Classify routing and select tool names for this turn."""
    available_set = frozenset(available)
    text = question.strip()
    if not text:
        return TurnIntent(routing="unknown", tool_names=available_set)

    matched_tools: set[str] = set()
    for family, pattern in _FAMILY_RES.items():
        if pattern.search(text):
            matched_tools |= _FAMILY_TOOLS[family]

    has_tools = bool(matched_tools)
    has_howto = bool(_HOW_TO_RE.search(text))
    is_neither = bool(_NEITHER_RE.match(text))

    if has_tools and has_howto:
        routing: RoutingLabel = "both"
        tool_names = frozenset(matched_tools) & available_set
    elif has_tools:
        routing = "tools"
        tool_names = frozenset(matched_tools) & available_set
    elif has_howto:
        routing = "docs"
        tool_names = frozenset()
    elif is_neither:
        routing = "neither"
        tool_names = frozenset()
    else:
        routing = "unknown"
        tool_names = available_set

    return TurnIntent(routing=routing, tool_names=tool_names)


def select_tools_for_question(
    question: str,
    *,
    available: Iterable[str],
) -> frozenset[str]:
    """Return tool names to inject for this turn."""
    return resolve_turn_intent(question, available=available).tool_names


def should_retrieve_docs(routing: RoutingLabel) -> bool:
    """Skip RAG on pure live-data and small-talk turns."""
    return routing in {"docs", "both", "unknown"}
