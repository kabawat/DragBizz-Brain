from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.observability.metrics import MetricsRegistry
from app.orchestrator.cancel import CancelScope
from app.schemas.chat import ChatRequest, ChatResponse

ChatHandler = Callable[..., Awaitable[ChatResponse]]
StreamEvent = tuple[str, dict[str, Any]]


async def stream_chat(
    handle_chat: ChatHandler,
    body: ChatRequest,
    *,
    user: dict[str, Any],
    request_id: str,
    store_id: str,
    access_token: str,
    metrics: MetricsRegistry | None,
    cancel: CancelScope | None = None,
) -> AsyncIterator[StreamEvent]:
    if metrics is not None:
        metrics.record_stream_request()
    started = time.perf_counter()
    ttft_recorded = False
    yield (
        "request.started",
        {
            "requestId": request_id,
            "sessionId": body.session_id,
        },
    )

    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

    async def _emit(event: str, payload: dict[str, Any]) -> None:
        await queue.put((event, payload))

    scope = cancel or CancelScope()

    async def _run() -> ChatResponse:
        return await handle_chat(
            body,
            user=user,
            request_id=request_id,
            store_id=store_id,
            access_token=access_token,
            cancel=scope,
            emit=_emit,
        )

    task = asyncio.create_task(_run())
    response: ChatResponse | None = None
    aborted = False
    try:
        while True:
            if scope.cancelled:
                aborted = True
                task.cancel()
                break
            if task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.05)
            except TimeoutError:
                if task.done():
                    while not queue.empty():
                        item = queue.get_nowait()
                        if item is not None:
                            yield item
                    break
                continue
            if item is None:
                break
            yield item

        try:
            response = await task
        except asyncio.CancelledError:
            aborted = True
            response = None
    except asyncio.CancelledError:
        aborted = True
        scope.cancel()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        response = None

    if aborted or response is None:
        if metrics is not None:
            metrics.record_stream_aborted()
            metrics.record_cancel()
        yield ("request.aborted", {"requestId": request_id})
        return

    message = response.message or ""
    chunk_size = 48
    for index in range(0, len(message), chunk_size):
        if scope.cancelled:
            if metrics is not None:
                metrics.record_stream_aborted()
                metrics.record_cancel()
            yield ("request.aborted", {"requestId": request_id})
            return
        delta = message[index : index + chunk_size]
        if not ttft_recorded and metrics is not None:
            metrics.record_stream_ttft((time.perf_counter() - started) * 1000)
            ttft_recorded = True
        yield ("assistant.delta", {"text": delta})

    pending_payload = None
    if response.pending_confirmation is not None:
        pending = response.pending_confirmation
        pending_payload = {
            "confirmationId": pending.confirmation_id,
            "draftId": pending.draft_id,
            "type": pending.type,
            "summary": pending.summary,
            "expiresAt": pending.expires_at,
        }
    if metrics is not None:
        metrics.record_stream_completed()
    yield (
        "request.completed",
        {
            "requestId": request_id,
            "sessionId": response.session_id,
            "provider": response.provider,
            "model": response.model,
            "pendingConfirmation": pending_payload,
        },
    )
