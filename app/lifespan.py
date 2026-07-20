import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_seconds)
    )
    app.state.http_client = http_client

    tool_registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        tool_registry.register_definition(definition)

    model_router = ModelRouter()
    if settings.openai_api_key:
        provider = OpenAICompatibleProvider(settings, http_client)
        model_router.register(provider)
        if settings.active_provider == provider.name:
            model_router.set_active(provider.name)
        elif settings.active_provider:
            logger.warning(
                "Active provider '%s' is not registered",
                settings.active_provider,
            )
    else:
        logger.warning("AI_OPENAI_API_KEY is not set; chat provider unavailable")

    gateway = AiGateway(model_router)
    app.state.model_router = model_router
    app.state.ai_gateway = gateway
    app.state.tool_registry = tool_registry
    app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=tool_registry,
        settings=settings,
    )

    logger.info("AI service started")
    try:
        yield
    finally:
        await http_client.aclose()
        logger.info("AI service stopped")
