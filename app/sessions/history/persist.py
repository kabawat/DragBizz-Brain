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
                serialized.append(
                    item.model_dump(by_alias=True, exclude_none=True)
                )
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

    def _done(done: asyncio.Task[None]) -> None:
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.warning(
                "Durable history background task failed for session %s: %s",
                session_id,
                exc,
            )

    task.add_done_callback(_done)
