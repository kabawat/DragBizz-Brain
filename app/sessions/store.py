"""Short-lived chat session memory (AI-only; not business data).

Package lives under app/sessions/ so Redis short-cache and Postgres durable
history can land as peer backends without moving orchestrator imports.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.core.exceptions import AppError
from app.rag.chunker import estimate_tokens
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolResult

Clock = Callable[[], float]


@dataclass(frozen=True)
class SessionTurn:
    user_text: str
    assistant_text: str
    # Compact tool snapshot so follow-ups can reuse prior live numbers/context.
    tool_context: str | None = None


@dataclass
class _SessionRecord:
    user_id: str
    store_id: str
    turns: list[SessionTurn] = field(default_factory=list)
    expires_at: float = 0.0


class SessionStore(Protocol):
    async def load_history(
        self, *, session_id: str, user_id: str, store_id: str
    ) -> list[SessionTurn]: ...

    async def append_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
        turn: SessionTurn,
    ) -> None: ...

    def compact_tool_context(self, tool_results: list[ToolResult]) -> str | None: ...


class InMemorySessionStore:
    """Process-local session memory with sliding TTL and ownership binding.

    Suitable until Redis (B1) is available. Not shared across workers.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 1_800,
        max_turns: int = 10,
        history_max_tokens: int = 2_000,
        tool_context_max_chars: int = 1_500,
        clock: Clock | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_turns = max_turns
        self._history_max_tokens = history_max_tokens
        self._tool_context_max_chars = tool_context_max_chars
        self._clock = clock or time.monotonic
        self._sessions: dict[str, _SessionRecord] = {}

    async def load_history(
        self, *, session_id: str, user_id: str, store_id: str
    ) -> list[SessionTurn]:
        record = self._get_active(session_id)
        if record is None:
            return []
        self._assert_owner(record, user_id=user_id, store_id=store_id)
        self._touch(record)
        return list(record.turns)

    async def append_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
        turn: SessionTurn,
    ) -> None:
        record = self._get_active(session_id)
        if record is None:
            record = _SessionRecord(user_id=user_id, store_id=store_id)
            self._sessions[session_id] = record
        else:
            self._assert_owner(record, user_id=user_id, store_id=store_id)

        record.turns.append(turn)
        record.turns = _trim_turns(
            record.turns,
            max_turns=self._max_turns,
            history_max_tokens=self._history_max_tokens,
        )
        self._touch(record)

    def compact_tool_context(self, tool_results: list[ToolResult]) -> str | None:
        if not tool_results:
            return None
        payload: list[dict[str, Any]] = [
            {"tool": result.tool, "success": result.success, "data": result.data}
            for result in tool_results
        ]
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > self._tool_context_max_chars:
            return text[: self._tool_context_max_chars - 3] + "..."
        return text

    def _get_active(self, session_id: str) -> _SessionRecord | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        if self._clock() >= record.expires_at:
            del self._sessions[session_id]
            return None
        return record

    def _touch(self, record: _SessionRecord) -> None:
        record.expires_at = self._clock() + self._ttl_seconds

    @staticmethod
    def _assert_owner(
        record: _SessionRecord, *, user_id: str, store_id: str
    ) -> None:
        if record.user_id != user_id or record.store_id != store_id:
            raise AppError(
                code="SESSION_FORBIDDEN",
                message="sessionId is not valid for this user and store",
                status_code=403,
            )


def turns_to_messages(turns: list[SessionTurn]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for turn in turns:
        messages.append(ChatMessage(role="user", content=turn.user_text))
        assistant = turn.assistant_text
        if turn.tool_context:
            assistant = (
                f"{turn.assistant_text}\n\n"
                f"[Prior tool results]\n{turn.tool_context}"
            )
        messages.append(ChatMessage(role="assistant", content=assistant))
    return messages


def _trim_turns(
    turns: list[SessionTurn],
    *,
    max_turns: int,
    history_max_tokens: int,
) -> list[SessionTurn]:
    trimmed = list(turns[-max_turns:]) if max_turns > 0 else []
    while len(trimmed) > 1 and _turns_tokens(trimmed) > history_max_tokens:
        trimmed.pop(0)
    return trimmed


def _turns_tokens(turns: list[SessionTurn]) -> int:
    total = 0
    for turn in turns:
        total += estimate_tokens(turn.user_text)
        total += estimate_tokens(turn.assistant_text)
        if turn.tool_context:
            total += estimate_tokens(turn.tool_context)
    return total
