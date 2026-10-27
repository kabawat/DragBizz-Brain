"""Deterministic conversational fast-path for DragBizz AI.

Handles pure greetings, live date/time questions, identity/help prompts,
and acknowledgments locally with zero LLM latency (< 30ms) and zero token cost.
Safely bypasses whenever business terms (sales, stock, expense, invoice, khata)
are detected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.dates import (
    current_ist_datetime_str,
    current_ist_human_str,
    current_ist_time_str,
)
from app.schemas.tool import ToolDefinition
from app.tools.capability_catalog import build_capability_help

# Business keywords that must NEVER be intercepted by conversational fast-path
_BUSINESS_DISQUALIFIERS = re.compile(
    r"\b("
    r"sale|sales|stock|item|product|samaan|maal|"
    r"expense|kharcha|kharch|cost|rent|kiraya|salary|pagar|"
    r"invoice|bill|draft|gst|tax|"
    r"customer|grahak|party|supplier|vendor|"
    r"khata|udhaar|due|jama|payment|balance|hisab|ledger|"
    r"rupaye|rupee|rs|inr|cash|\d+"
    r")\b",
    re.IGNORECASE,
)

# 1. Greetings
_GREETING_RE = re.compile(
    r"^(hi|hy|hii+|hello|helo|hlo|hey|yo|"
    r"namaste|namaskar|pranam|kem cho|kya haal hai|kaise ho|sab badhiya|"
    r"radhe radhe|ram ram|jai shree krishna|jai shree ram|"
    r"good morning|good afternoon|good evening|good day)\W*$",
    re.IGNORECASE,
)

# 2. Date queries
_DATE_QUERY_RE = re.compile(
    r"^(aaj kya date he|aaj kya date hai|aaj ki date|date kya hai|"
    r"aaj kon sa din he|aaj kya din hai|today date|what is today(?:'s)? date|"
    r"what is the date|date)\W*$",
    re.IGNORECASE,
)

# 3. Time queries
_TIME_QUERY_RE = re.compile(
    r"^(time|time kya hua|time kya hua hai|exact time batao|exact time|"
    r"abhi kya time ho raha hai|abhi kya time hai|what time is it|"
    r"current time|samay kya hai|samay)\W*$",
    re.IGNORECASE,
)

# 4. Combined Date & Time queries
_DATETIME_QUERY_RE = re.compile(
    r"^(date and time|time and date|aaj ki date aur time|date aur time)\W*$",
    re.IGNORECASE,
)

# 5. Bot Identity & Capabilities
_IDENTITY_RE = re.compile(
    r"^(?:/?help|how do i use dragbizz chat|dragbizz chat kaise use karein|"
    r"aap kaun ho|tum kaun ho|who are you|aapka naam kya hai|tumhara naam kya hai|"
    r"tum kya kar sakte ho|aap kya kar sakte ho|kya kar sakte ho|"
    r"help chahiye|help|kya help kar sakte ho|kya kaam karte ho)\W*$",
    re.IGNORECASE,
)

# 6. Acknowledgments & Closures
_CLOSURE_RE = re.compile(
    r"^(theek hai|thik hai|ok|okay|accha|achha|got it|samajh gaya|"
    r"dhanyawad|shukriya|thanks|thank you(?:\s+bhai)?|thank u|"
    r"bye|alvida|good night|see you|tata)\W*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FastConversationalOutcome:
    message: str
    tool_calls: list[Any]
    tool_results: list[Any]


def try_fast_conversational_turn(
    question: str,
    *,
    language: str = "hi-IN",
    user_name: str = "",
    capabilities: list[ToolDefinition] | tuple[ToolDefinition, ...] = (),
) -> FastConversationalOutcome | None:
    """Return an instant response for pure conversational queries, or None.

    Ensures zero model latency (< 30ms) for greetings, time, date, and basic help.
    Strictly yields to the orchestrator if any business entity is present.
    """
    text = question.strip()
    if not text:
        return None

    # Safety: If any business keyword or number/amount is in the query, don't intercept.
    if _BUSINESS_DISQUALIFIERS.search(text):
        return None

    is_english = language.lower().startswith("en")
    clean_name = user_name.strip().split()[0] if user_name.strip() else ""
    salutation = f" {clean_name}" if clean_name else ""

    # 1. Pure Greetings
    if _GREETING_RE.match(text):
        if is_english:
            msg = (
                f"Hello{salutation}! Welcome to DragBizz. "
                "How can I assist you with your store today — check sales, "
                "manage stock, or record an expense? 😊"
            )
        else:
            msg = (
                f"Namaste{salutation}! DragBizz me aapka swagat hai. "
                "Aaj store me kya check karna hai — sales, stock ya koi "
                "kharcha add karna hai? 😊"
            )
        return FastConversationalOutcome(message=msg, tool_calls=[], tool_results=[])

    # 2. Date queries
    if _DATE_QUERY_RE.match(text):
        human_date = current_ist_human_str()
        if is_english:
            msg = f"Today is **{human_date}** (IST). 😊"
        else:
            msg = f"Aaj **{human_date}** hai. 😊"
        return FastConversationalOutcome(message=msg, tool_calls=[], tool_results=[])

    # 3. Time queries
    if _TIME_QUERY_RE.match(text):
        current_time = current_ist_time_str()
        if is_english:
            msg = f"The current time is **{current_time}** (IST). 😊"
        else:
            msg = f"Abhi exact time **{current_time}** (IST) ho raha hai. 😊"
        return FastConversationalOutcome(message=msg, tool_calls=[], tool_results=[])

    # 4. Combined Date & Time queries
    if _DATETIME_QUERY_RE.match(text):
        full_dt = current_ist_datetime_str()
        if is_english:
            msg = f"Currently it is **{full_dt}**. 😊"
        else:
            msg = f"Abhi **{full_dt}** ho raha hai. 😊"
        return FastConversationalOutcome(message=msg, tool_calls=[], tool_results=[])

    # 5. Identity & Capabilities
    if _IDENTITY_RE.match(text):
        msg = build_capability_help(capabilities, language=language)
        return FastConversationalOutcome(message=msg, tool_calls=[], tool_results=[])

    # 6. Acknowledgments & Closures
    if _CLOSURE_RE.match(text):
        if is_english:
            msg = "You're welcome! Feel free to ask anytime. Have a productive day! 👍"
        else:
            msg = (
                "Koi baat nahi dost! Jab bhi store ka koi kaam ho, bas bataiye. "
                "Have a great day! 👍"
            )
        return FastConversationalOutcome(message=msg, tool_calls=[], tool_results=[])

    return None
