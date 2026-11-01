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

_INTERNAL_DISCLOSURE_PATTERNS = (
    r"\bsystem\s+prompt\b",
    r"\bdeveloper\s+(?:prompt|instructions?|message)\b",
    r"\bhidden\s+(?:prompt|instructions?)\b",
    r"\binitialization\s+(?:text|instructions?)\b",
    r"\bsecurity\s+and\s+grounding\s+rules\b",
    r"\b(?:traceback \(most recent call last\)|stack trace)\b",
    r"^\s*File \"[^\"]+\", line \d+",
)
_INTERNAL_DISCLOSURE_RE = re.compile(
    "|".join(_INTERNAL_DISCLOSURE_PATTERNS), re.IGNORECASE | re.MULTILINE
)

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
        self,
        text: str,
        tool_results: list[ToolResult],
        prior_numbers: set[str] | None = None,
        protected_prompt: str | None = None,
    ) -> OutputGuardDecision:
        secret = _SECRET_RE.search(text)
        if secret:
            return OutputGuardDecision(
                allowed=False,
                category="SECRET_LEAK",
                matched=secret.group(0),
                sanitized_text=_SECRET_RE.sub(_REDACTED, text),
            )

        internal = _INTERNAL_DISCLOSURE_RE.search(text)
        if internal or _contains_prompt_excerpt(text, protected_prompt):
            return OutputGuardDecision(
                allowed=False,
                category="INTERNAL_DISCLOSURE",
                matched=internal.group(0) if internal else "system prompt excerpt",
                sanitized_text="",
            )

        if _is_raw_json_document(text):
            return OutputGuardDecision(
                allowed=False,
                category="RAW_JSON",
                matched="JSON document",
                sanitized_text="",
            )

        unsupported = self._first_unsupported_amount(
            text, tool_results, prior_numbers=prior_numbers
        )
        if unsupported is not None:
            return OutputGuardDecision(
                allowed=False,
                category="UNSUPPORTED_NUMBERS",
                matched=unsupported,
                sanitized_text=text,
            )

        return OutputGuardDecision(allowed=True, sanitized_text=text)

    def _first_unsupported_amount(
        self,
        text: str,
        tool_results: list[ToolResult],
        prior_numbers: set[str] | None = None,
    ) -> str | None:
        amounts = [
            (match.group(0), _normalize_amount(match.group(1) or match.group(2)))
            for match in _CURRENCY_RE.finditer(text)
        ]
        if not amounts:
            return None
        known = _numbers_in_tool_results(tool_results)
        if prior_numbers:
            known.update(prior_numbers)
        for raw, normalized in amounts:
            if normalized not in known:
                return raw
        return None


def _is_raw_json_document(text: str) -> bool:
    """Reject a response that is itself a raw JSON object/array."""
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
        if candidate[:4].lower() == "json":
            candidate = candidate[4:].strip()
    if not candidate.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, (dict, list))


def _contains_prompt_excerpt(text: str, protected_prompt: str | None) -> bool:
    if not protected_prompt:
        return False
    normalized_text = " ".join(text.split()).casefold()
    prompt_lines = (
        " ".join(line.split()).casefold() for line in protected_prompt.splitlines()
    )
    return any(len(line) >= 80 and line in normalized_text for line in prompt_lines)
