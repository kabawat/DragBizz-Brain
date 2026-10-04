"""Turn intent: routing label + capability set for this user message.

Routing labels are ``tools`` / ``docs`` / ``both`` / ``neither``.
Unmatched questions are ``unknown`` and receive read tools only.
Write and sensitive names come from longer action phrases in the
current user text. History, tool results, and retrieved docs are
not inputs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

RoutingLabel = Literal["tools", "docs", "both", "neither", "unknown"]

# Read tools offered when the question matches no family, or when it
# matches a family but not an action phrase. A newly registered write
# or sensitive tool stays out of this set until an exposure map names it.
_READ_TOOLS = frozenset(
    {
        "search_product",
        "today_sale",
        "stock_summary",
        "search_customer",
        "payment_history",
    }
)

# Reads for a matched family. Writes and sensitive tools are added
# separately, and only from the longer phrases in _FAMILY_CUES.
_FAMILY_READS: dict[str, frozenset[str]] = {
    "sale": frozenset({"today_sale"}),
    "stock": frozenset({"stock_summary", "search_product"}),
    "product": frozenset({"search_product"}),
    "payment": frozenset({"payment_history", "search_customer"}),
    "customer": frozenset({"search_customer", "payment_history"}),
    "invoice": frozenset({"search_customer", "search_product"}),
}

# Longer family phrases only. Short Phase 1 tokens (payment, jama,
# debit, release) stay in _SENSITIVE_ACTION_CUES and do not grant
# exposure by themselves.
_EXPOSURE: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (
        (
            "naya customer",
            "customer banao",
            "customer bana",
            "create customer",
            "create a customer",
            "create a new customer",
            "create new customer",
            "add customer",
            "add a customer",
            "add a new customer",
            "add new customer",
            "customer create",
            "customer add",
        ),
        frozenset({"create_customer"}),
    ),
    (
        ("update customer", "customer update"),
        frozenset({"update_customer"}),
    ),
    (
        ("ledger credit", "jama karo", "payment record"),
        frozenset({"ledger_credit"}),
    ),
    (
        ("ledger debit", "udhaar add", "udhaar dalo"),
        frozenset({"ledger_debit"}),
    ),
    (
        (
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
            "bill for",
            "ke liye bill",
            "ke liye invoice",
        ),
        frozenset(
            {
                "create_customer",
                "create_invoice_draft",
                "update_invoice_draft",
            }
        ),
    ),
    (
        ("release invoice", "release the draft", "release draft"),
        frozenset({"release_invoice"}),
    ),
)

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
        "payment aaye",
        "payments aaye",
    ),
    "customer": (
        "customer",
        "khata",
        "udhaar",
        "gstin",
        "baaki",
        "baqi",
        "naya customer",
        "customer banao",
        "customer bana",
        "create customer",
        "create a customer",
        "create a new customer",
        "create new customer",
        "add customer",
        "add a customer",
        "add a new customer",
        "add new customer",
        "customer create",
        "customer add",
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

# Docs/FAQ path when no tool family matched.
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

# Whole-message small talk.
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
_EXPOSURE_RES = tuple(
    (
        re.compile(
            "|".join(re.escape(cue) for cue in cues),
            re.IGNORECASE,
        ),
        names,
    )
    for cues, names in _EXPOSURE
)

# Explicit user wording required before a sensitive tool may be staged.
# Phrases are the action cues already used by the family lists, plus the
# short action words (payment, jama, debit, release).
_SENSITIVE_ACTION_CUES: dict[str, tuple[str, ...]] = {
    "release_invoice": (
        *tuple(cue for cue in _FAMILY_CUES["invoice"] if cue.startswith("release")),
        "release",
    ),
    "ledger_credit": (
        "ledger credit",
        "jama karo",
        "payment record",
        "jama",
        "payment",
    ),
    "ledger_debit": (
        "ledger debit",
        "udhaar add",
        "udhaar dalo",
        "debit",
    ),
}
_SENSITIVE_ACTION_RES = {
    name: re.compile("|".join(re.escape(cue) for cue in cues), re.IGNORECASE)
    for name, cues in _SENSITIVE_ACTION_CUES.items()
    if cues
}


@dataclass(frozen=True)
class TurnIntent:
    routing: RoutingLabel
    tool_names: frozenset[str]


def _exposure_tools(text: str) -> set[str]:
    names: set[str] = set()
    for pattern, tools in _EXPOSURE_RES:
        if pattern.search(text):
            names |= tools
    return names


def resolve_turn_intent(
    question: str,
    *,
    available: Iterable[str],
) -> TurnIntent:
    """Classify routing and the capability set for this user message.

    The set is computed from ``question`` only. Callers must not pass
    history, tool JSON, or retrieved documentation.
    """
    available_set = frozenset(available)
    text = question.strip()
    read_only = _READ_TOOLS & available_set
    if not text:
        return TurnIntent(routing="unknown", tool_names=read_only)

    matched_reads: set[str] = set()
    for family, pattern in _FAMILY_RES.items():
        if pattern.search(text):
            matched_reads |= _FAMILY_READS[family]

    has_tools = bool(matched_reads)
    has_howto = bool(_HOW_TO_RE.search(text))
    is_neither = bool(_NEITHER_RE.match(text))

    if has_tools and has_howto:
        routing: RoutingLabel = "both"
        tool_names = frozenset(matched_reads) & available_set
    elif has_tools:
        routing = "tools"
        tool_names = (matched_reads | _exposure_tools(text)) & available_set
    elif has_howto:
        routing = "docs"
        tool_names = frozenset()
    elif is_neither:
        routing = "neither"
        tool_names = frozenset()
    else:
        routing = "unknown"
        tool_names = read_only

    return TurnIntent(routing=routing, tool_names=tool_names)


def select_tools_for_question(
    question: str,
    *,
    available: Iterable[str],
) -> frozenset[str]:
    """Return tool names to inject for this turn."""
    return resolve_turn_intent(question, available=available).tool_names


def user_requested_sensitive_action(question: str, tool_name: str) -> bool:
    """True when the user text itself asks for this sensitive action.

    A tool result or retrieved document must not be enough to stage a
    khata write or an invoice release.
    """
    pattern = _SENSITIVE_ACTION_RES.get(tool_name)
    if pattern is None:
        return False
    return bool(pattern.search(question.strip()))


def should_retrieve_docs(routing: RoutingLabel) -> bool:
    """Skip RAG on pure live-data and small-talk turns."""
    return routing in {"docs", "both", "unknown"}
