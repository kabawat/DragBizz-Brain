"""Time and date resolution utilities with India Standard Time (IST) support."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_TODAY_KEYWORDS = (r"\baaj\b", r"\btoday\b", r"\babhi\b", r"\bcurrent\b")
_YESTERDAY_KEYWORDS = (r"\bkal\b", r"\byesterday\b")
_DAY_BEFORE_KEYWORDS = (r"\bparso\b", r"\bday before yesterday\b")


def now_ist() -> datetime:
    """Return current time in India Standard Time (UTC+05:30)."""
    return datetime.now(IST)


def current_ist_date_str() -> str:
    """Return current date formatted as YYYY-MM-DD in IST."""
    return now_ist().strftime("%Y-%m-%d")


def current_ist_human_str() -> str:
    """Return human readable date e.g. 'Monday, 19 October 2026'."""
    return now_ist().strftime("%A, %d %B %Y")


def current_ist_time_str() -> str:
    """Return human readable time in IST e.g. '03:00 PM'."""
    return now_ist().strftime("%I:%M %p")


def current_ist_datetime_str() -> str:
    """Return full date and time e.g. 'Monday, 19 October 2026, 03:00 PM IST'."""
    return now_ist().strftime("%A, %d %B %Y, %I:%M %p IST")


def resolve_expense_date(raw_date: str | None, context_text: str = "") -> str:
    """Resolve expense date to a valid ISO YYYY-MM-DD string.

    Prevents LLM date hallucinations (e.g. inventing 2025-01-24 from pretraining cutoff)
    when the user asks for 'aaj' / 'today' or leaves the date to default.
    """
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    text_lower = (context_text or "").lower()

    # 1. Explicit keyword checks in user request
    if any(re.search(pat, text_lower) for pat in _TODAY_KEYWORDS):
        return today_str

    if any(re.search(pat, text_lower) for pat in _DAY_BEFORE_KEYWORDS):
        return (now - timedelta(days=2)).strftime("%Y-%m-%d")

    if any(re.search(pat, text_lower) for pat in _YESTERDAY_KEYWORDS):
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # 2. Check raw_date passed by LLM / caller
    if isinstance(raw_date, str) and raw_date.strip():
        cleaned = raw_date.strip()[:10]
        try:
            parsed = datetime.strptime(cleaned, "%Y-%m-%d")
            # If the year is older than current year (e.g. 2025 or 2024 when now
            # is 2026), it is an LLM pre-training cutoff artifact.
            if parsed.year < now.year:
                return today_str
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 3. Default to today
    return today_str


def format_iso_to_ist(val: object) -> str:
    """Convert an ISO datetime string or datetime object to an IST formatted string."""
    if not val:
        return ""
    if isinstance(val, str):
        try:
            iso = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST).strftime("%Y-%m-%d %I:%M %p IST")
        except Exception:
            return val
    if isinstance(val, datetime):
        dt = (
            val.astimezone(IST)
            if val.tzinfo
            else val.replace(tzinfo=timezone.utc).astimezone(IST)
        )
        return dt.strftime("%Y-%m-%d %I:%M %p IST")
    return str(val)
