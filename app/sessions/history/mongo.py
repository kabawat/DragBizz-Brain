from __future__ import annotations

import uuid
from typing import Any

from app.sessions.history.models import (
    DEFAULT_LIST_LIMIT,
    MESSAGES_COLLECTION,
    SESSIONS_COLLECTION,
    HistoryMessage,
    HistorySessionDetail,
    HistorySessionSummary,
    as_dt,
    title_from_text,
    utcnow,
)
from app.sessions.history.ownership import assert_owner_doc, not_found


class MongoHistoryStore:
    def __init__(self, db: Any) -> None:
        self._sessions = db[SESSIONS_COLLECTION]
        self._messages = db[MESSAGES_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self._sessions.create_index(
            [("userId", 1), ("storeId", 1), ("updatedAt", -1)],
            name="user_store_updated",
        )
        await self._messages.create_index(
            [("sessionId", 1), ("createdAt", 1)],
            name="session_created",
        )

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
        existing = await self._sessions.find_one({"_id": session_id})
        if existing is None:
            await self._sessions.insert_one(
                {
                    "_id": session_id,
                    "userId": user_id,
                    "storeId": store_id,
                    "title": title_from_text(user_text),
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
        else:
            assert_owner_doc(existing, user_id=user_id, store_id=store_id)
            await self._sessions.update_one(
                {"_id": session_id},
                {"$set": {"updatedAt": now}},
            )

        await self._messages.insert_many(
            [
                {
                    "_id": str(uuid.uuid4()),
                    "sessionId": session_id,
                    "role": "user",
                    "content": user_text,
                    "toolResults": None,
                    "createdAt": now,
                },
                {
                    "_id": str(uuid.uuid4()),
                    "sessionId": session_id,
                    "role": "assistant",
                    "content": assistant_text,
                    "toolResults": tool_results,
                    "createdAt": now,
                },
            ]
        )

    async def list_sessions(
        self,
        *,
        user_id: str,
        store_id: str,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[HistorySessionSummary]:
        cursor = (
            self._sessions.find({"userId": user_id, "storeId": store_id})
            .sort("updatedAt", -1)
            .limit(max(1, min(limit, 100)))
        )
        rows: list[HistorySessionSummary] = []
        async for doc in cursor:
            rows.append(
                HistorySessionSummary(
                    id=str(doc["_id"]),
                    title=str(doc.get("title") or "New chat"),
                    created_at=as_dt(doc.get("createdAt")),
                    updated_at=as_dt(doc.get("updatedAt")),
                )
            )
        return rows

    async def get_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> HistorySessionDetail:
        doc = await self._sessions.find_one({"_id": session_id})
        if doc is None:
            raise not_found()
        assert_owner_doc(doc, user_id=user_id, store_id=store_id)
        messages: list[HistoryMessage] = []
        cursor = self._messages.find({"sessionId": session_id}).sort(
            "createdAt", 1
        )
        async for item in cursor:
            tool_results = item.get("toolResults")
            messages.append(
                HistoryMessage(
                    id=str(item["_id"]),
                    role=str(item.get("role") or "assistant"),
                    content=str(item.get("content") or ""),
                    created_at=as_dt(item.get("createdAt")),
                    tool_results=tool_results
                    if isinstance(tool_results, list)
                    else None,
                )
            )
        return HistorySessionDetail(
            id=session_id,
            title=str(doc.get("title") or "New chat"),
            created_at=as_dt(doc.get("createdAt")),
            updated_at=as_dt(doc.get("updatedAt")),
            messages=messages,
        )

    async def delete_session(
        self,
        *,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> None:
        doc = await self._sessions.find_one({"_id": session_id})
        if doc is None:
            raise not_found()
        assert_owner_doc(doc, user_id=user_id, store_id=store_id)
        await self._messages.delete_many({"sessionId": session_id})
        await self._sessions.delete_one({"_id": session_id})
