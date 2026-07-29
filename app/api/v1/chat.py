from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.orchestrator.chat_service import ChatService
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    assert_valid_store_id,
)

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
    return await chat_service.handle(
        body,
        user=user,
        request_id=getattr(request.state, "request_id", None) or "",
        store_id=store_id,
        access_token=access_token,
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
    return await chat_service.confirm(
        body,
        user=user,
        request_id=getattr(request.state, "request_id", None) or "",
        store_id=store_id,
        access_token=access_token,
    )
