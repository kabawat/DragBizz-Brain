"""Strip secret / payment / PII-shaped keys from structured log extras."""

from __future__ import annotations

from typing import Any

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "bearer",
    "upi",
    "accountnumber",
    "account_number",
    "bankaccount",
    "bank_account",
    "ifsc",
    "cardnumber",
    "card_number",
    "cvv",
    "pan",
    "aadhaar",
    "aadhar",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    if normalized in {"token", "authorization", "password", "secret"}:
        return True
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact_mapping(value: Any) -> Any:
    """Recursively redact sensitive keys. Never used for tool payloads (those
    must not be logged at all)."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_mapping(item)
        return redacted
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return value
