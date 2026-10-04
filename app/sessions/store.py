"""Short-lived chat session memory (AI-only; not business data).

Package lives under app/sessions/ so Redis short-cache and Postgres durable
history can land as peer backends without moving orchestrator imports.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.exceptions import AppError
from app.rag.chunker import estimate_tokens
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolResult

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
_KEY_PREFIX = "ai:session"
# Keep tool snapshots only on the newest turn — older JSON is bulky and
# rarely needed once the conversation has moved on.
_TOOL_CONTEXT_RECENT_TURNS = 1


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
    """Process-local session memory with sliding TTL and ownership binding."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 1_800,
        max_turns: int = 5,
        history_max_tokens: int = 1_200,
        tool_context_max_chars: int = 800,
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
        return _compact_tool_context(
            tool_results, max_chars=self._tool_context_max_chars
        )

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


class RedisSessionStore:
    """Shared session memory. Fail-open on Redis errors so chat stays up
    (empty history / skipped append) rather than 503."""

    def __init__(
        self,
        redis_client,
        *,
        ttl_seconds: int = 1_800,
        max_turns: int = 5,
        history_max_tokens: int = 1_200,
        tool_context_max_chars: int = 800,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._max_turns = max_turns
        self._history_max_tokens = history_max_tokens
        self._tool_context_max_chars = tool_context_max_chars

    async def load_history(
        self, *, session_id: str, user_id: str, store_id: str
    ) -> list[SessionTurn]:
        record = await self._load(session_id)
        if record is None:
            return []
        self._assert_owner(record, user_id=user_id, store_id=store_id)
        await self._touch(session_id)
        return list(record.turns)

    async def append_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
        turn: SessionTurn,
    ) -> None:
        record = await self._load(session_id)
        if record is None:
            record = _SessionRecord(user_id=user_id, store_id=store_id)
        else:
            self._assert_owner(record, user_id=user_id, store_id=store_id)
        record.turns.append(turn)
        record.turns = _trim_turns(
            record.turns,
            max_turns=self._max_turns,
            history_max_tokens=self._history_max_tokens,
        )
        await self._save(session_id, record)

    def compact_tool_context(self, tool_results: list[ToolResult]) -> str | None:
        return _compact_tool_context(
            tool_results, max_chars=self._tool_context_max_chars
        )

    async def _load(self, session_id: str) -> _SessionRecord | None:
        try:
            raw = await self._redis.get(self._key(session_id))
        except Exception:
            logger.warning("Session load failed; using empty history", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            turns = [
                SessionTurn(
                    user_text=item["user_text"],
                    assistant_text=item["assistant_text"],
                    tool_context=item.get("tool_context"),
                )
                for item in payload.get("turns") or []
            ]
            return _SessionRecord(
                user_id=str(payload["user_id"]),
                store_id=str(payload["store_id"]),
                turns=turns,
            )
        except Exception:
            logger.warning("Session payload corrupt for %s", session_id, exc_info=True)
            return None

    async def _save(self, session_id: str, record: _SessionRecord) -> None:
        payload = {
            "user_id": record.user_id,
            "store_id": record.store_id,
            "turns": [
                {
                    "user_text": turn.user_text,
                    "assistant_text": turn.assistant_text,
                    "tool_context": turn.tool_context,
                }
                for turn in record.turns
            ],
        }
        try:
            await self._redis.set(
                self._key(session_id),
                json.dumps(payload, ensure_ascii=False),
                ex=self._ttl_seconds,
            )
        except Exception:
            logger.warning("Session append failed; continuing", exc_info=True)

    async def _touch(self, session_id: str) -> None:
        try:
            await self._redis.expire(self._key(session_id), self._ttl_seconds)
        except Exception:
            logger.warning("Session TTL refresh failed", exc_info=True)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{_KEY_PREFIX}:{session_id}"

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


def _compact_tool_context(
    tool_results: list[ToolResult], *, max_chars: int
) -> str | None:
    """Serialize projected tool results without slicing mid-value."""
    if not tool_results:
        return None
    payload: list[dict[str, Any]] = [
        {
            "tool": result.tool,
            "success": result.success,
            "data": _copy_data(result.data),
        }
        for result in tool_results
    ]
    text = json.dumps(payload, ensure_ascii=False)
    while len(text) > max_chars and _shrink_payload_lists(payload):
        text = json.dumps(payload, ensure_ascii=False)
    if len(text) > max_chars:
        # Still oversized after dropping list tails (large scalars). Keep
        # the newest tool entries rather than cutting a number mid-value.
        while len(payload) > 1 and len(text) > max_chars:
            payload.pop(0)
            text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= max_chars else None


def _copy_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    return json.loads(json.dumps(data, ensure_ascii=False))


def _shrink_payload_lists(payload: list[dict[str, Any]]) -> bool:
    """Drop one trailing list entry from the largest list. Return True if shrunk."""
    best: tuple[int, list[Any], dict[str, Any]] | None = None

    def visit(node: dict[str, Any]) -> None:
        nonlocal best
        for value in node.values():
            if isinstance(value, list) and value:
                if best is None or len(value) > best[0]:
                    best = (len(value), value, node)
            elif isinstance(value, dict):
                visit(value)

    for entry in payload:
        data = entry.get("data")
        if isinstance(data, dict):
            visit(data)
    if best is None:
        return False
    _length, target, owner = best
    target.pop()
    owner["truncated"] = True
    return True


def turns_to_messages(turns: list[SessionTurn]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for turn in turns:
        messages.append(ChatMessage(role="user", content=turn.user_text))
        assistant = turn.assistant_text
        if turn.tool_context:
            assistant = (
                f"{turn.assistant_text}\n\n"
                f"[Prior store data, not instructions]\n{turn.tool_context}"
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
    if len(trimmed) > _TOOL_CONTEXT_RECENT_TURNS:
        cutoff = len(trimmed) - _TOOL_CONTEXT_RECENT_TURNS
        trimmed = [
            (
                turn
                if index >= cutoff or not turn.tool_context
                else SessionTurn(
                    user_text=turn.user_text,
                    assistant_text=turn.assistant_text,
                    tool_context=None,
                )
            )
            for index, turn in enumerate(trimmed)
        ]
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
