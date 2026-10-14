from __future__ import annotations

from typing import Any

from app.sessions.history.models import (
    DEFAULT_LIST_LIMIT,
    HistorySessionDetail,
    HistorySessionSummary,
)
from app.sessions.history.ownership import not_found


class NoOpHistoryStore:
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
        return None

    async def list_sessions(
        self,
        *,
        user_id: str,
        store_id: str,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[HistorySessionSummary]:
        return []

    async def get_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> HistorySessionDetail:
        raise not_found()

    async def delete_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> None:
        raise not_found()
