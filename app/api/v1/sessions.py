from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.core.security import get_current_user
from app.core.store_access import authorize_store_access
from app.schemas.chat import assert_valid_store_id
from app.schemas.history import (
    ChatHistoryMessage,
    ChatSessionDetail,
    ChatSessionListResponse,
    ChatSessionSummary,
)
from app.sessions import NoOpHistoryStore

router = APIRouter(tags=["chat-sessions"])


def _history_store(request: Request):
    return getattr(request.app.state, "history_store", None) or NoOpHistoryStore()


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@router.get(
    "/chat/sessions",
    response_model=ChatSessionListResponse,
    response_model_by_alias=True,
)
async def list_chat_sessions(
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    storeId: str = "",
) -> ChatSessionListResponse:
    store_id = assert_valid_store_id(storeId)
    await authorize_store_access(request, user, store_id)
    rows = await _history_store(request).list_sessions(
        user_id=str(user["sub"]),
        store_id=store_id,
    )
    return ChatSessionListResponse(
        sessions=[
            ChatSessionSummary(
                id=row.id,
                title=row.title,
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
            )
            for row in rows
        ]
    )


@router.get(
    "/chat/sessions/{session_id}",
    response_model=ChatSessionDetail,
    response_model_by_alias=True,
)
async def get_chat_session(
    session_id: str,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    storeId: str = "",
) -> ChatSessionDetail:
    store_id = assert_valid_store_id(storeId)
    await authorize_store_access(request, user, store_id)
    detail = await _history_store(request).get_session(
        session_id=session_id,
        user_id=str(user["sub"]),
        store_id=store_id,
    )
    return ChatSessionDetail(
        id=detail.id,
        title=detail.title,
        created_at=_iso(detail.created_at),
        updated_at=_iso(detail.updated_at),
        messages=[
            ChatHistoryMessage(
                id=msg.id,
                role=msg.role if msg.role in ("user", "assistant") else "assistant",
                content=msg.content,
                created_at=_iso(msg.created_at),
                tool_results=msg.tool_results,
            )
            for msg in detail.messages
        ],
    )


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_chat_session(
    session_id: str,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    storeId: str = "",
) -> Response:
    store_id = assert_valid_store_id(storeId)
    await authorize_store_access(request, user, store_id)
    await _history_store(request).delete_session(
        session_id=session_id,
        user_id=str(user["sub"]),
        store_id=store_id,
    )
    return Response(status_code=204)
