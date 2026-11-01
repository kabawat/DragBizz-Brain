from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.exceptions import AppError
from app.sessions.history.noop import NoOpHistoryStore
from app.sessions.history.protocol import DurableHistoryStore

logger = logging.getLogger(__name__)


async def persist_turn_safe(
    history: DurableHistoryStore | None,
    *,
    session_id: str,
    user_id: str,
    store_id: str,
    user_text: str,
    assistant_text: str,
    tool_results: list[Any] | None = None,
) -> None:
    if history is None or isinstance(history, NoOpHistoryStore):
        return
    serialized: list[dict[str, Any]] | None = None
    if tool_results:
        serialized = []
        for item in tool_results:
            if hasattr(item, "model_dump"):
                serialized.append(item.model_dump(by_alias=True, exclude_none=True))
            elif isinstance(item, dict):
                serialized.append(item)
    try:
        await history.append_messages(
            session_id=session_id,
            user_id=user_id,
            store_id=store_id,
            user_text=user_text,
            assistant_text=assistant_text,
            tool_results=serialized,
        )
    except AppError:
        logger.error(
            "Durable history ownership error for session %s",
            session_id,
            exc_info=True,
        )
    except Exception:
        logger.warning(
            "Durable history write failed for session %s",
            session_id,
            exc_info=True,
        )


_PENDING_PERSIST_TASKS: set[asyncio.Task[None]] = set()


def get_pending_persist_tasks() -> set[asyncio.Task[None]]:
    """Return an immutable snapshot of currently in-flight persist tasks."""
    return set(_PENDING_PERSIST_TASKS)


def schedule_persist_turn(
    history: DurableHistoryStore | None,
    *,
    session_id: str,
    user_id: str,
    store_id: str,
    user_text: str,
    assistant_text: str,
    tool_results: list[Any] | None = None,
) -> None:
    """Fire-and-forget durable write so chat TTFT is not blocked by Mongo."""
    if history is None or isinstance(history, NoOpHistoryStore):
        return
    task = asyncio.create_task(
        persist_turn_safe(
            history,
            session_id=session_id,
            user_id=user_id,
            store_id=store_id,
            user_text=user_text,
            assistant_text=assistant_text,
            tool_results=tool_results,
        )
    )
    _PENDING_PERSIST_TASKS.add(task)

    def _done(done: asyncio.Task[None]) -> None:
        _PENDING_PERSIST_TASKS.discard(done)
        if done.cancelled():
            return
        try:
            exc = done.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning(
                "Durable history background task failed for session %s: %s",
                session_id,
                exc,
            )

    task.add_done_callback(_done)


async def drain_pending_persist_tasks(timeout: float = 5.0) -> int:
    """Await active in-flight persist tasks up to timeout seconds during shutdown.

    Note: In-memory task tracking buffers tasks across the process lifespan,
    but does not provide crash-proof durability against ungraceful SIGKILL, OOM,
    or power loss.
    """
    if not _PENDING_PERSIST_TASKS:
        return 0
    tasks = list(_PENDING_PERSIST_TASKS)
    logger.info(
        "Draining %d pending history persistence tasks (timeout=%.1fs)",
        len(tasks),
        timeout,
    )
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for t in done:
        if not t.cancelled():
            try:
                exc = t.exception()
                if exc is not None:
                    logger.warning(
                        "History persistence task completed with error: %s", exc
                    )
            except asyncio.CancelledError:
                pass
    if pending:
        logger.warning(
            "%d history persistence tasks exceeded the shutdown timeout of "
            "%.1fs; cancelling",
            len(pending),
            timeout,
        )
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return len(done)
