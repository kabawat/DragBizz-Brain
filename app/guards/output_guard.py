"""Outbound checks: scrub leaked secrets; flag currency amounts not backed by tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.schemas.tool import ToolResult

_REDACTED = "[REDACTED]"

_SECRET_PATTERNS = (
    # OpenAI-style API keys.
    r"\bsk-[A-Za-z0-9_-]{16,}\b",
    # JWTs (three base64url segments starting with eyJ).
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    # Bearer tokens.
    r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*",
    # AWS access key IDs.
    r"\bAKIA[A-Z0-9]{16}\b",
    # Connection strings with embedded credentials.
    r"\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|redis|amqp|mysql)://[^\s'\"]+",
    # key/token/password/secret assignments with a non-trivial value.
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret"
    r"|password|passwd|secret)\s*[:=]\s*['\"]?[A-Za-z0-9@#$%^&*._+/-]{8,}",
)

_SECRET_RE = re.compile("|".join(_SECRET_PATTERNS), re.IGNORECASE)

# ₹1,200 / Rs. 1200.50 / 1200 rupees / 1,200 rs
# "rs"/"inr" must not be the tail of a word ("ledgers.") and the amount must
# be on the same line — otherwise numbered lists after a word ending in "rs"
# get flagged as currency.
_CURRENCY_RE = re.compile(
    r"(?:₹|(?<![a-z])rs\.?|(?<![a-z])inr)[ \t]*([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"|([0-9][0-9,]*(?:\.[0-9]+)?)[ \t]*(?:rupees?|rupaye|rs\b)",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")


@dataclass(frozen=True)
class OutputGuardDecision:
    allowed: bool
    category: str | None = None
    matched: str | None = None
    # Message with secrets redacted; equals the original when nothing matched.
    sanitized_text: str = ""


def _normalize_amount(raw: str) -> str:
    """'1,200.00' -> '1200' ; '1200.50' -> '1200.5'."""
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _numbers_in_tool_results(tool_results: list[ToolResult]) -> set[str]:
    numbers: set[str] = set()
    for result in tool_results:
        blob = json.dumps(result.data or {})
        for match in _NUMBER_RE.finditer(blob):
            numbers.add(_normalize_amount(match.group(0)))
    return numbers


class OutputGuard:
    def evaluate(
        self, text: str, tool_results: list[ToolResult]
    ) -> OutputGuardDecision:
        secret = _SECRET_RE.search(text)
        if secret:
            return OutputGuardDecision(
                allowed=False,
                category="SECRET_LEAK",
                matched=secret.group(0),
                sanitized_text=_SECRET_RE.sub(_REDACTED, text),
            )

        unsupported = self._first_unsupported_amount(text, tool_results)
        if unsupported is not None:
            return OutputGuardDecision(
                allowed=False,
                category="UNSUPPORTED_NUMBERS",
                matched=unsupported,
                sanitized_text=text,
            )

        return OutputGuardDecision(allowed=True, sanitized_text=text)

    def _first_unsupported_amount(
        self, text: str, tool_results: list[ToolResult]
    ) -> str | None:
        amounts = [
            (match.group(0), _normalize_amount(match.group(1) or match.group(2)))
            for match in _CURRENCY_RE.finditer(text)
        ]
        if not amounts:
            return None
        known = _numbers_in_tool_results(tool_results)
        for raw, normalized in amounts:
            if normalized not in known:
                return raw
        return None
