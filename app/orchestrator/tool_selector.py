"""Turn intent: routing label + exposed tools for this message."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

_PRIOR_EXPOSURE_TURNS = 4

RoutingLabel = Literal["tools", "docs", "both", "neither", "unknown"]

# Default reads when no write exposure matches.
_READ_TOOLS = frozenset(
    {
        "search_product",
        "today_sale",
        "stock_summary",
        "product_summary",
        "search_customer",
        "payment_history",
        "list_stores",
        "customer_summary",
        "get_customer_ledger",
        "list_customer_accounts",
        "get_customer_payment",
        "list_payment_reminders",
        "invoice_summary",
    }
)

_FAMILY_READS: dict[str, frozenset[str]] = {
    "sale": frozenset({"today_sale", "invoice_summary"}),
    "stock": frozenset({"stock_summary", "search_product"}),
    "product": frozenset({"search_product"}),
    "product_stats": frozenset({"product_summary"}),
    "payment": frozenset({"payment_history", "search_customer"}),
    "payment_detail": frozenset({"get_customer_payment", "payment_history"}),
    "payment_reminders": frozenset(
        {"list_payment_reminders", "search_customer"}
    ),
    # Lookup/create flows need search only; payment history is payment-family.
    "customer": frozenset({"search_customer"}),
    "customer_ledger": frozenset({"get_customer_ledger", "search_customer"}),
    "customer_accounts": frozenset(
        {"list_customer_accounts", "search_customer"}
    ),
    "customer_stats": frozenset({"customer_summary"})-,
    "invoice": frozenset({"search_customer", "search_product"}),
    "invoice_stats": frozenset({"invoice_summary", "today_sale"}),
    "store": frozenset({"list_stores"}),
}

# Write tools from action phrases (not short sensitive tokens alone).
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
        (
            "update customer",
            "customer update",
            "edit customer",
            "customer edit",
            "update email",
            "email update",
            "email badlo",
            "email change",
            "email add",
            "add email",
            "email bhi",
            "email daal",
            "email dalo",
            "email daalo",
            "update phone",
            "phone update",
            "number update",
            "phone badlo",
            "number badlo",
            "update details",
            "details update",
            "update address",
            "address update",
            "address badlo",
            "address add",
            "add address",
            "update gst",
            "gst update",
            "gst add",
            "add gst",
            "gstin add",
            "add gstin",
            "company name",
            "update note",
            "note add",
            "add note",
        ),
        frozenset({"update_customer"}),
    ),
    (
        (
            "merge customer",
            "merge customers",
            "customer merge",
            "duplicate merge",
            "merge duplicate",
            "customers merge",
            "merge karo",
            "merge kar do",
        ),
        frozenset({"merge_customers", "search_customer"}),
    ),
    (
        (
            "opening balance",
            "set opening balance",
            "opening balance set",
            "khata opening",
            "opening khata",
            "shuruati balance",
            "opening due",
        ),
        frozenset({"set_opening_balance", "search_customer"}),
    ),
    (
        (
            "formal payment",
            "structured payment",
            "invoice payment",
            "payment entry",
            "record payment formal",
            "upi payment record",
            "cash payment record",
            "bank payment record",
        ),
        frozenset({"record_customer_payment", "search_customer"}),
    ),
    (
        (
            "update payment note",
            "payment note update",
            "payment notes",
            "edit payment",
        ),
        frozenset({"update_customer_payment"}),
    ),
    (
        (
            "collect link",
            "payment link",
            "payment collect",
            "collect payment link",
            "create collect link",
            "payment link banao",
            "collect link banao",
        ),
        frozenset({"create_collect_link", "search_customer"}),
    ),
    (
        (
            "payment reminder",
            "send reminder",
            "reminder bhejo",
            "reminder send",
            "due reminder",
            "payment yaad dilao",
            "khata reminder",
        ),
        frozenset({"send_payment_reminder", "search_customer"}),
    ),
    (
        (
            "ledger credit",
            "jama karo",
            "jama kar diya",
            "jama kar",
            "jama diya",
            "jama de diya",
            "jama daal",
            "jama dalo",
            "jama add",
            "payment record",
            "payment add",
            "payment mila",
            "payment liya",
            "payment le liya",
            "paid karo",
            "khata jama",
            "credit add",
        ),
        frozenset({"ledger_credit"}),
    ),
    (
        (
            "ledger debit",
            "udhaar add",
            "udhaar dalo",
            "udhar add",
            "udhar dalo",
            "udhaar le",
            "udhar le",
            "udhaar laga",
            "udhar laga",
            "mere se udhaar",
            "mere se udhar",
            "khate me add",
            "khata me add",
            "khate mein add",
            "khata mein add",
            "khate me daal",
            "khata me daal",
            "due add",
            "debit add",
        ),
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
    (
        (
            "stock add",
            "add stock",
            "stock badhao",
            "stock badha",
            "stock daalo",
            "stock dalo",
            "stock daal",
            "stock me add",
            "stock mein add",
            "stock me daal",
            "stock mein daal",
            "inventory add",
            "add inventory",
            "unit add",
            "units add",
            "units daalo",
            "units dalo",
            "stock in",
            "stock intake",
            "maal aaya",
            "maal add",
            "stock update",
        ),
        frozenset({"add_stock", "search_product"}),
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
    "product_stats": (
        "total product",
        "total products",
        "kitne product",
        "kitane product",
        "kitna product",
        "kitne products",
        "kitane products",
        "how many product",
        "how many products",
        "product listed",
        "products listed",
        "listed product",
        "listed products",
        "product count",
        "products count",
        "product total",
        "products total",
        "catalog me",
        "catalogue me",
        "kitne sku",
        "kitane sku",
        "total sku",
        "total skus",
    ),
    "payment": (
        "payments",
        "payment history",
        "payment dikhao",
        "recent payment",
        "payment aaye",
        "payments aaye",
    ),
    "payment_detail": (
        "payment detail",
        "payment details",
        "ek payment",
        "payment id",
        "get payment",
    ),
    "payment_reminders": (
        "payment reminders",
        "list reminders",
        "reminder list",
        "reminders dikhao",
        "reminder history",
    ),
    "customer": (
        "customer",
        "khata",
        "khate",
        "udhaar",
        "udhar",
        "account",
        "hisab",
        "dues",
        "gstin",
        "baaki",
        "baqi",
        "ka number",
        "ki number",
        "mobile number",
        "phone number",
        "opening balance",
        "merge customer",
        "merge customers",
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
        "edit customer",
        "customer edit",
        "update email",
        "email update",
        "email badlo",
        "email change",
        "email add",
        "add email",
        "email bhi",
        "email daal",
        "email dalo",
        "email daalo",
        "update phone",
        "phone update",
        "number update",
        "phone badlo",
        "number badlo",
        "update details",
        "details update",
        "update address",
        "address update",
        "update gst",
        "gst update",
        "gst add",
        "add gst",
        "ledger credit",
        "ledger debit",
        "udhaar add",
        "udhaar dalo",
        "udhar add",
        "udhar dalo",
        "udhaar le",
        "udhar le",
        "mere se udhaar",
        "mere se udhar",
        "khate me add",
        "khata me add",
        "jama karo",
        "jama kar diya",
        "jama kar",
        "jama diya",
        "jama daal",
        "payment record",
        "payment add",
        "payment mila",
        "khata jama",
    ),
    "customer_ledger": (
        "customer ledger",
        "khata ledger",
        "ledger dikhao",
        "ledger lines",
        "ledger history",
        "khata history",
        "transaction history",
    ),
    "customer_accounts": (
        "due list",
        "dues list",
        "accounts due",
        "due customers",
        "jin ke due",
        "due wale",
        "customers with due",
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
    "store": (
        "store ka name",
        "store ka naam",
        "store name",
        "store naam",
        "mere store",
        "mera store",
        "my store",
        "kitane store",
        "kitne store",
        "kitna store",
        "how many store",
        "how many stores",
        "total store",
        "total stores",
        "stores list",
        "store list",
        "saare store",
        "saare stores",
        "all stores",
        "active store",
        "store ki category",
        "store category",
        "store ka category",
        "meri category",
        "mere store ki category",
        "category kya",
        "category batao",
        "category ke according",
        "category ke accrding",
        "category according",
        "kaunse product",
        "konsa product",
        "kya product",
        "product suggest",
        "products suggest",
        "product suggestion",
        "kya stock karu",
        "kya stock karna",
        "store karne chahiye",
        "stock karne chahiye",
        "kya rakhu",
        "kya rakhna",
    ),
    "customer_stats": (
        "total customer",
        "total customers",
        "kitne customer",
        "kitane customer",
        "kitna customer",
        "kitne customers",
        "kitane customers",
        "how many customer",
        "how many customers",
        "customer count",
        "customers count",
        "customer total",
        "customers total",
        "aaj ke customer",
        "aaj ke customers",
        "today customer",
        "today customers",
        "new customer",
        "new customers",
        "naye customer",
        "naye customers",
    ),
    "invoice_stats": (
        "total invoice",
        "total invoices",
        "total bill",
        "total bills",
        "kitne invoice",
        "kitane invoice",
        "kitna invoice",
        "kitne bill",
        "kitane bill",
        "kitna bill",
        "how many invoice",
        "how many invoices",
        "how many bill",
        "how many bills",
        "invoice count",
        "invoices count",
        "bill count",
        "bills count",
        "aaj ki invoice",
        "aaj ke invoice",
        "aaj ka invoice",
        "aaj ki bill",
        "aaj ke bill",
        "today invoice",
        "todays invoice",
        "today's invoice",
        "today invoices",
        "todays invoices",
        "today's invoices",
        "today bill",
        "todays bill",
        "today's bill",
        "last 7 day",
        "last 7 days",
        "last7 day",
        "last7 days",
        "last seven day",
        "last seven days",
        "pichle 7 din",
        "pichhle 7 din",
        "7 din ki invoice",
        "7 din ke invoice",
        "7 days invoice",
        "7 day invoice",
        "hafta invoice",
        "hafte ki invoice",
        "hafte ke bill",
        "weekly invoice",
        "weekly bill",
        "last 15 day",
        "last 15 days",
        "last 30 day",
        "last 30 days",
        "pichle 30 din",
        "is mahine",
        "is month",
        "this month",
    ),
}

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

# Sensitive tools need explicit user wording before staging.
_SENSITIVE_ACTION_CUES: dict[str, tuple[str, ...]] = {
    "release_invoice": (
        *tuple(cue for cue in _FAMILY_CUES["invoice"] if cue.startswith("release")),
        "release",
    ),
    "ledger_credit": (
        "ledger credit",
        "jama karo",
        "jama kar diya",
        "jama kar",
        "jama diya",
        "jama de diya",
        "jama daal",
        "jama dalo",
        "jama add",
        "payment record",
        "payment add",
        "payment mila",
        "payment liya",
        "paid karo",
        "khata jama",
        "credit add",
        "jama",
        "payment",
    ),
    "ledger_debit": (
        "ledger debit",
        "udhaar add",
        "udhaar dalo",
        "udhar add",
        "udhar dalo",
        "udhaar le",
        "udhar le",
        "udhaar laga",
        "udhar laga",
        "mere se udhaar",
        "mere se udhar",
        "khate me add",
        "khata me add",
        "khate mein add",
        "khata mein add",
        "khate me daal",
        "khata me daal",
        "due add",
        "debit add",
        "udhaar",
        "udhar",
        "debit",
    ),
    "add_stock": (
        "stock add",
        "add stock",
        "stock badhao",
        "stock badha",
        "stock daalo",
        "stock dalo",
        "stock daal",
        "stock me add",
        "stock mein add",
        "stock me daal",
        "stock mein daal",
        "inventory add",
        "add inventory",
        "unit add",
        "units add",
        "units daalo",
        "units dalo",
        "stock in",
        "stock intake",
        "maal aaya",
        "maal add",
        "stock update",
        "liye the",
        "liya tha",
        "se liye",
        "se liya",
    ),
    "merge_customers": (
        "merge customer",
        "merge customers",
        "customer merge",
        "duplicate merge",
        "merge duplicate",
        "customers merge",
        "merge karo",
        "merge kar do",
    ),
    "set_opening_balance": (
        "opening balance",
        "set opening balance",
        "opening balance set",
        "khata opening",
        "opening khata",
        "shuruati balance",
        "opening due",
    ),
    "record_customer_payment": (
        "formal payment",
        "structured payment",
        "invoice payment",
        "payment entry",
        "upi payment record",
        "cash payment record",
        "bank payment record",
    ),
    "update_customer_payment": (
        "update payment note",
        "payment note update",
        "payment notes",
        "edit payment",
    ),
    "create_collect_link": (
        "collect link",
        "payment link",
        "payment collect",
        "collect payment link",
        "create collect link",
        "payment link banao",
        "collect link banao",
    ),
    "send_payment_reminder": (
        "payment reminder",
        "send reminder",
        "reminder bhejo",
        "reminder send",
        "due reminder",
        "payment yaad dilao",
        "khata reminder",
    ),
}
_SENSITIVE_ACTION_RES = {
    name: re.compile("|".join(re.escape(cue) for cue in cues), re.IGNORECASE)
    for name, cues in _SENSITIVE_ACTION_CUES.items()
    if cues
}

# Amount may sit between "khate me" and "add" ("khate me 100 add kar do").
_LEDGER_DEBIT_FLEX_RE = re.compile(
    r"khate?\s+me(?:in)?\s+(?:\S+\s+){0,4}(?:add|daal|dalo)\b"
    r"|(?:add|daal|dalo)\s+(?:kar(?:o|u|un|oon| do| dena)?)?\s*"
    r".{0,24}\b(?:khata|khate|udhaar|udhar)\b"
    r"|\bmere\s+se\s+udha?ar\b",
    re.IGNORECASE,
)
_LEDGER_CREDIT_FLEX_RE = re.compile(
    r"khate?\s+me(?:in)?\s+(?:\S+\s+){0,4}(?:jama|payment|paid)\b"
    r"|(?:jama|payment|paid)\s+(?:\S+\s+){0,4}\b(?:khata|khate)\b",
    re.IGNORECASE,
)
# Amount/name may sit between "stock me" and "add" ("stock me 10 add kar do").
_STOCK_ADD_FLEX_RE = re.compile(
    r"stock\s+me(?:in)?\s+(?:\S+\s+){0,6}(?:add|daal|dalo|badha)\b"
    r"|(?:add|daal|dalo|badha)\s+(?:\S+\s+){0,4}\bstock\b"
    r"|\b(?:unit|units)\s+(?:\S+\s+){0,4}(?:add|daal|dalo)\b"
    r"|\b(?:liye|liya)\s+(?:the|tha|thi)\b"
    r"|\bse\s+liye?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TurnIntent:
    routing: RoutingLabel
    tool_names: frozenset[str]


def _exposure_tools(text: str) -> set[str]:
    names: set[str] = set()
    for pattern, tools in _EXPOSURE_RES:
        if pattern.search(text):
            names |= tools
    if _LEDGER_DEBIT_FLEX_RE.search(text):
        names.add("ledger_debit")
    if _LEDGER_CREDIT_FLEX_RE.search(text):
        names.add("ledger_credit")
    if _STOCK_ADD_FLEX_RE.search(text):
        names.update({"add_stock", "search_product"})
    return names


def _prior_exposure_tools(prior_user_texts: Sequence[str] | None) -> set[str]:
    if not prior_user_texts:
        return set()
    names: set[str] = set()
    for text in prior_user_texts[-_PRIOR_EXPOSURE_TURNS:]:
        if isinstance(text, str) and text.strip():
            names |= _exposure_tools(text)
    return names


def resolve_turn_intent(
    question: str,
    *,
    available: Iterable[str],
    prior_user_texts: Sequence[str] | None = None,
) -> TurnIntent:
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
        # Keep prior writes + apply current-turn exposure cues.
        carried = _prior_exposure_tools(prior_user_texts)
        current = _exposure_tools(text)
        tool_names = (read_only | carried | current) & available_set

    return TurnIntent(routing=routing, tool_names=tool_names)


def user_requested_sensitive_action(question: str, tool_name: str) -> bool:
    """True if user text itself asks for this sensitive action."""
    text = question.strip()
    if tool_name == "ledger_debit" and _LEDGER_DEBIT_FLEX_RE.search(text):
        return True
    if tool_name == "ledger_credit" and _LEDGER_CREDIT_FLEX_RE.search(text):
        return True
    if tool_name == "add_stock" and _STOCK_ADD_FLEX_RE.search(text):
        return True
    pattern = _SENSITIVE_ACTION_RES.get(tool_name)
    if pattern is None:
        return False
    return bool(pattern.search(text))


def should_retrieve_docs(
    routing: RoutingLabel,
    *,
    tool_names: frozenset[str] | None = None,
) -> bool:
    """Skip RAG on tool-only turns and write follow-ups."""
    if routing in {"docs", "both"}:
        return True
    if routing != "unknown":
        return False
    if tool_names is not None and tool_names - _READ_TOOLS:
        return False
    return True


_PHONE_RE = re.compile(r"^[\d\s+\-]{8,16}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def looks_like_field_fill(text: str) -> bool:
    """Short name / phone / email replies in multi-turn write flows."""
    value = text.strip()
    if not value or len(value) > 64:
        return False
    if _PHONE_RE.fullmatch(value) or _EMAIL_RE.fullmatch(value):
        return True
    if len(value.split()) > 4:
        return False
    if _HOW_TO_RE.search(value) or _NEITHER_RE.match(value):
        return False
    for pattern in _FAMILY_RES.values():
        if pattern.search(value):
            return False
    return True


def narrow_field_fill_tools(tool_names: frozenset[str]) -> frozenset[str]:
    """Keep write tools + minimal companion reads for field-fill turns."""
    writes = tool_names - _READ_TOOLS
    if not writes:
        return tool_names
    companions: set[str] = set()
    if writes & {"create_customer", "update_customer"}:
        companions.add("search_customer")
    if writes & {
        "create_invoice_draft",
        "update_invoice_draft",
        "release_invoice",
    }:
        companions.update({"search_customer", "search_product"})
    if writes & {"ledger_credit", "ledger_debit"}:
        companions.update({"search_customer", "payment_history"})
    if writes & {
        "merge_customers",
        "set_opening_balance",
        "record_customer_payment",
        "create_collect_link",
        "send_payment_reminder",
    }:
        companions.add("search_customer")
    if writes & {"update_customer_payment"}:
        companions.update({"payment_history", "get_customer_payment"})
    if writes & {"add_stock"}:
        companions.add("search_product")
    return frozenset(writes | (companions & tool_names))
