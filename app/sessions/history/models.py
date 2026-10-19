from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SESSIONS_COLLECTION = "ai_chat_sessions"
MESSAGES_COLLECTION = "ai_chat_messages"
DEFAULT_LIST_LIMIT = 40
TITLE_MAX_LEN = 42


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return utcnow()


def title_from_text(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "New chat"
    if len(cleaned) > TITLE_MAX_LEN:
        return f"{cleaned[:TITLE_MAX_LEN]}…"
    return cleaned


@dataclass(frozen=True)
class HistoryMessage:
    id: str
    role: str
    content: str
    created_at: datetime
    tool_results: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class HistorySessionSummary:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HistorySessionDetail:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[HistoryMessage] = field(default_factory=list)
