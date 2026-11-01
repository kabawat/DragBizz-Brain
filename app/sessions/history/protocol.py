from __future__ import annotations

from typing import Any, Protocol

from app.sessions.history.models import (
    DEFAULT_LIST_LIMIT,
    HistorySessionDetail,
    HistorySessionSummary,
)


class DurableHistoryStore(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def append_messages(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
        user_text: str,
        assistant_text: str,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> None: ...

    async def list_sessions(
        self,
        *,
        user_id: str,
        store_id: str,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[HistorySessionSummary]: ...

    async def get_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> HistorySessionDetail: ...

    async def delete_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> None: ...
