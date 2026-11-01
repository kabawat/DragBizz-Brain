import httpx
from fastapi import Request

from app.api.v1.chat import get_chat_service
from app.core.security import get_current_user

__all__ = ["get_chat_service", "get_current_user", "get_http_client"]


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client
