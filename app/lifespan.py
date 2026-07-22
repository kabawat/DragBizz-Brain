import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerClient
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_seconds)
    )
    app.state.http_client = http_client

    retailer = RetailerClient(http_client, settings.retailer_service_url)
    tool_registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        handler = READ_TOOL_HANDLERS[definition.name]
        tool_registry.register(definition, handler)

    tool_executor = ToolExecutor(registry=tool_registry, retailer=retailer)

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
    app.state.retailer_client = retailer
    app.state.tool_executor = tool_executor
    app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=tool_registry,
        settings=settings,
        tool_executor=tool_executor,
    )

    logger.info("AI service started")
    try:
        yield
    finally:
        await http_client.aclose()
        logger.info("AI service stopped")
