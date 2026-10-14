from __future__ import annotations

import uuid
from typing import Any

from app.sessions.history.models import (
    DEFAULT_LIST_LIMIT,
    HistoryMessage,
    HistorySessionDetail,
    HistorySessionSummary,
    title_from_text,
    utcnow,
)
from app.sessions.history.ownership import assert_owner_memory, not_found


class InMemoryHistoryStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, list[HistoryMessage]] = {}

    async def ensure_indexes(self) -> None:
        return None

    async def append_messages(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
        user_text: str,
        assistant_text: str,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> None:
        now = utcnow()
        existing = self._sessions.get(session_id)
        if existing is None:
            self._sessions[session_id] = {
                "user_id": user_id,
                "store_id": store_id,
                "title": title_from_text(user_text),
                "created_at": now,
                "updated_at": now,
            }
            self._messages[session_id] = []
        else:
            assert_owner_memory(existing, user_id=user_id, store_id=store_id)
            existing["updated_at"] = now

        msgs = self._messages[session_id]
        msgs.append(
            HistoryMessage(
                id=str(uuid.uuid4()),
                role="user",
                content=user_text,
                created_at=now,
            )
        )
        msgs.append(
            HistoryMessage(
                id=str(uuid.uuid4()),
                role="assistant",
                content=assistant_text,
                created_at=now,
                tool_results=tool_results,
            )
        )

    async def list_sessions(
        self,
        *,
        user_id: str,
        store_id: str,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[HistorySessionSummary]:
        rows = [
            HistorySessionSummary(
                id=sid,
                title=str(meta["title"]),
                created_at=meta["created_at"],
                updated_at=meta["updated_at"],
            )
            for sid, meta in self._sessions.items()
            if meta["user_id"] == user_id and meta["store_id"] == store_id
        ]
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows[: max(1, min(limit, 100))]

    async def get_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> HistorySessionDetail:
        meta = self._sessions.get(session_id)
        if meta is None:
            raise not_found()
        assert_owner_memory(meta, user_id=user_id, store_id=store_id)
        return HistorySessionDetail(
            id=session_id,
            title=str(meta["title"]),
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
            messages=list(self._messages.get(session_id) or []),
        )

    async def delete_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> None:
        meta = self._sessions.get(session_id)
        if meta is None:
            raise not_found()
        assert_owner_memory(meta, user_id=user_id, store_id=store_id)
        del self._sessions[session_id]
        self._messages.pop(session_id, None)
