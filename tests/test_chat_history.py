"""Durable chat history store ownership + listing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.exceptions import AppError
from app.sessions.history import (
    InMemoryHistoryStore,
    NoOpHistoryStore,
    drain_pending_persist_tasks,
    get_pending_persist_tasks,
    persist_turn_safe,
    schedule_persist_turn,
    title_from_text,
)

USER = "user-1"
OTHER_USER = "user-2"
STORE = "a" * 24
OTHER_STORE = "b" * 24
SESSION = "sess-history-1"


@pytest.mark.asyncio
async def test_append_list_get_delete_roundtrip() -> None:
    store = InMemoryHistoryStore()
    await store.append_messages(
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="Aaj kitni sale hui?",
        assistant_text="Aaj ki sale ₹12,000 hai.",
        tool_results=[{"tool": "daily_sales", "success": True}],
    )
    await store.append_messages(
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="Stock check",
        assistant_text="Stock theek hai.",
    )

    listed = await store.list_sessions(user_id=USER, store_id=STORE)
    assert len(listed) == 1
    assert listed[0].id == SESSION
    assert listed[0].title == "Aaj kitni sale hui?"

    detail = await store.get_session(
        session_id=SESSION, user_id=USER, store_id=STORE
    )
    assert len(detail.messages) == 4
    assert detail.messages[0].role == "user"
    assert detail.messages[1].role == "assistant"
    assert detail.messages[1].tool_results is not None

    await store.delete_session(session_id=SESSION, user_id=USER, store_id=STORE)
    listed_after = await store.list_sessions(user_id=USER, store_id=STORE)
    assert listed_after == []


@pytest.mark.asyncio
async def test_list_orders_by_updated_at_desc() -> None:
    store = InMemoryHistoryStore()
    await store.append_messages(
        session_id="old",
        user_id=USER,
        store_id=STORE,
        user_text="Old chat",
        assistant_text="ok",
    )
    await store.append_messages(
        session_id="new",
        user_id=USER,
        store_id=STORE,
        user_text="New chat",
        assistant_text="ok",
    )
    # Touch old so it becomes newest
    await store.append_messages(
        session_id="old",
        user_id=USER,
        store_id=STORE,
        user_text="Bump",
        assistant_text="ok",
    )
    listed = await store.list_sessions(user_id=USER, store_id=STORE)
    assert [row.id for row in listed] == ["old", "new"]


@pytest.mark.asyncio
async def test_wrong_store_forbidden_on_get() -> None:
    store = InMemoryHistoryStore()
    await store.append_messages(
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="Hello",
        assistant_text="Hi",
    )
    with pytest.raises(AppError) as exc:
        await store.get_session(
            session_id=SESSION, user_id=USER, store_id=OTHER_STORE
        )
    assert exc.value.code == "SESSION_FORBIDDEN"
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_wrong_user_forbidden_on_delete() -> None:
    store = InMemoryHistoryStore()
    await store.append_messages(
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="Hello",
        assistant_text="Hi",
    )
    with pytest.raises(AppError) as exc:
        await store.delete_session(
            session_id=SESSION, user_id=OTHER_USER, store_id=STORE
        )
    assert exc.value.code == "SESSION_FORBIDDEN"


@pytest.mark.asyncio
async def test_not_found() -> None:
    store = InMemoryHistoryStore()
    with pytest.raises(AppError) as exc:
        await store.get_session(
            session_id="missing", user_id=USER, store_id=STORE
        )
    assert exc.value.code == "SESSION_NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_noop_list_empty() -> None:
    store = NoOpHistoryStore()
    assert await store.list_sessions(user_id=USER, store_id=STORE) == []


@pytest.mark.asyncio
async def test_persist_turn_safe_swallows_errors() -> None:
    class BoomStore(InMemoryHistoryStore):
        async def append_messages(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("mongo down")

    await persist_turn_safe(
        BoomStore(),
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="x",
        assistant_text="y",
    )


def test_title_from_text_truncates() -> None:
    long = "a" * 50
    title = title_from_text(long)
    assert title.endswith("…")
    assert len(title) == 43


@pytest.mark.asyncio
async def test_persist_task_tracking_and_completion() -> None:
    store = InMemoryHistoryStore()
    schedule_persist_turn(
        store,
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="test q",
        assistant_text="test a",
    )
    pending = get_pending_persist_tasks()
    assert len(pending) >= 1
    drained = await drain_pending_persist_tasks(timeout=2.0)
    assert drained >= 1
    assert len(get_pending_persist_tasks()) == 0
    detail = await store.get_session(session_id=SESSION, user_id=USER, store_id=STORE)
    assert len(detail.messages) == 2


@pytest.mark.asyncio
async def test_persist_task_exception_handled_cleanly() -> None:
    class ErrorStore(InMemoryHistoryStore):
        async def append_messages(self, **kwargs: Any) -> None:
            raise RuntimeError("Database connection died")

    schedule_persist_turn(
        ErrorStore(),
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="q",
        assistant_text="a",
    )
    drained = await drain_pending_persist_tasks(timeout=2.0)
    assert drained >= 1
    assert len(get_pending_persist_tasks()) == 0


@pytest.mark.asyncio
async def test_persist_task_timeout_cancellation() -> None:
    class StalledStore(InMemoryHistoryStore):
        async def append_messages(self, **kwargs: Any) -> None:
            await asyncio.sleep(5.0)

    schedule_persist_turn(
        StalledStore(),
        session_id=SESSION,
        user_id=USER,
        store_id=STORE,
        user_text="stalled q",
        assistant_text="stalled a",
    )
    # Bounded shutdown: timeout at 0.05s cancels stalled tasks
    drained = await drain_pending_persist_tasks(timeout=0.05)
    assert drained == 0
    assert len(get_pending_persist_tasks()) == 0
