import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.core.store_access import authorize_store_access
from app.limits.concurrency import Lease
from app.observability.context import reset_auth_context, set_auth_context
from app.observability.events import (
    LIMIT_CONCURRENCY,
    LIMIT_RATE,
    emit_event,
)
from app.orchestrator.cancel import CancelScope
from app.orchestrator.chat_service import ChatService
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    assert_valid_store_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    service = getattr(request.app.state, "chat_service", None)
    if service is None:
        raise AppError(
            code="AI_PROVIDER_NOT_CONFIGURED",
            message="Chat service is not initialized",
            status_code=503,
        )
    return service


async def _watch_disconnect(request: Request, cancel: CancelScope) -> None:
    try:
        while not cancel.cancelled:
            if await request.is_disconnected():
                cancel.cancel()
                return
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        return


@router.post("/chat", response_model=ChatResponse, response_model_by_alias=True)
async def chat(
    body: ChatRequest,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    store_id = assert_valid_store_id(body.store_id)
    access_token = getattr(request.state, "access_token", None)
    if not access_token:
        raise AppError(
            code="AUTH_MISSING",
            message="Access token missing or invalid",
            status_code=401,
        )
    await authorize_store_access(request, user, store_id)
    user_id = str(user["sub"])
    auth_tokens = set_auth_context(
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
    )
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    concurrency_gate = getattr(request.app.state, "concurrency_gate", None)
    lease: Lease | None = None
    cancel = CancelScope()
    watcher: asyncio.Task[None] | None = None
    try:
        if rate_limiter is not None:
            try:
                await rate_limiter.check_chat(user_id=user_id, store_id=store_id)
            except AppError as exc:
                if exc.code == "AI_RATE_LIMITED":
                    emit_event(LIMIT_RATE, kind="chat")
                raise
        if concurrency_gate is not None:
            try:
                lease = await concurrency_gate.acquire_chat(
                    user_id=user_id, store_id=store_id
                )
            except AppError as exc:
                if exc.code == "AI_CONCURRENCY_LIMIT":
                    emit_event(LIMIT_CONCURRENCY, kind="chat")
                raise
        watcher = asyncio.create_task(_watch_disconnect(request, cancel))
        return await chat_service.handle(
            body,
            user=user,
            request_id=getattr(request.state, "request_id", None) or "",
            store_id=store_id,
            access_token=access_token,
            cancel=cancel,
        )
    finally:
        cancel.cancel()
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        if concurrency_gate is not None and lease is not None:
            try:
                await concurrency_gate.release(lease)
            except Exception:
                logger.warning(
                    "Failed to release concurrency lease in chat endpoint",
                    exc_info=True,
                )
        reset_auth_context(auth_tokens)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    store_id = assert_valid_store_id(body.store_id)
    access_token = getattr(request.state, "access_token", None)
    if not access_token:
        raise AppError(
            code="AUTH_MISSING",
            message="Access token missing or invalid",
            status_code=401,
        )
    await authorize_store_access(request, user, store_id)
    user_id = str(user["sub"])
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    concurrency_gate = getattr(request.app.state, "concurrency_gate", None)
    lease: Lease | None = None
    cancel = CancelScope()

    # Bind only for preflight checks/emits in this handler context, then
    # clear — StreamingResponse runs the body iterator in another Context.
    preflight = set_auth_context(
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
    )
    try:
        if rate_limiter is not None:
            try:
                await rate_limiter.check_chat(user_id=user_id, store_id=store_id)
            except AppError as exc:
                if exc.code == "AI_RATE_LIMITED":
                    emit_event(LIMIT_RATE, kind="chat")
                raise
        if concurrency_gate is not None:
            try:
                lease = await concurrency_gate.acquire_chat(
                    user_id=user_id, store_id=store_id
                )
            except AppError as exc:
                if exc.code == "AI_CONCURRENCY_LIMIT":
                    emit_event(LIMIT_CONCURRENCY, kind="chat")
                raise
    finally:
        reset_auth_context(preflight)

    request_id = getattr(request.state, "request_id", None) or ""

    async def event_bytes() -> AsyncIterator[bytes]:
        # Set + reset in the same streaming Context as the iterator body.
        auth_tokens = set_auth_context(
            user_id=user_id,
            store_id=store_id,
            session_id=body.session_id,
        )
        watcher = asyncio.create_task(_watch_disconnect(request, cancel))
        try:
            async for name, payload in chat_service.handle_stream(
                body,
                user=user,
                request_id=request_id,
                store_id=store_id,
                access_token=access_token,
                cancel=cancel,
            ):
                data = json.dumps(payload, ensure_ascii=False)
                frame = f"event: {name}\ndata: {data}\n\n"
                yield frame.encode("utf-8")
        finally:
            cancel.cancel()
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            if concurrency_gate is not None and lease is not None:
                try:
                    await concurrency_gate.release(lease)
                except Exception:
                    logger.warning(
                        "Failed to release concurrency lease in chat_stream",
                        exc_info=True,
                    )
            reset_auth_context(auth_tokens)

    return StreamingResponse(
        event_bytes(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/chat/confirm",
    response_model=ChatResponse,
    response_model_by_alias=True,
)
async def confirm_chat(
    body: ConfirmRequest,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    store_id = assert_valid_store_id(body.store_id)
    access_token = getattr(request.state, "access_token", None)
    if not access_token:
        raise AppError(
            code="AUTH_MISSING",
            message="Access token missing or invalid",
            status_code=401,
        )
    await authorize_store_access(request, user, store_id)
    user_id = str(user["sub"])
    auth_tokens = set_auth_context(
        user_id=user_id,
        store_id=store_id,
        session_id=body.session_id,
    )
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    concurrency_gate = getattr(request.app.state, "concurrency_gate", None)
    lease: Lease | None = None
    try:
        if rate_limiter is not None:
            try:
                await rate_limiter.check_confirm(user_id=user_id, store_id=store_id)
            except AppError as exc:
                if exc.code == "AI_RATE_LIMITED":
                    emit_event(LIMIT_RATE, kind="confirm")
                raise
        if concurrency_gate is not None:
            try:
                lease = await concurrency_gate.acquire_confirm(
                    user_id=user_id, store_id=store_id
                )
            except AppError as exc:
                if exc.code == "AI_CONCURRENCY_LIMIT":
                    emit_event(LIMIT_CONCURRENCY, kind="confirm")
                raise
        return await chat_service.confirm(
            body,
            user=user,
            request_id=getattr(request.state, "request_id", None) or "",
            store_id=store_id,
            access_token=access_token,
        )
    finally:
        if concurrency_gate is not None and lease is not None:
            try:
                await concurrency_gate.release(lease)
            except Exception:
                logger.warning(
                    "Failed to release concurrency lease in confirm_chat",
                    exc_info=True,
                )
        reset_auth_context(auth_tokens)
