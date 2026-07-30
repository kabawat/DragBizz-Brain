import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.confirmations import InMemoryConfirmationStore, RedisConfirmationStore
from app.executors.tool_executor import ToolExecutor
from app.idempotency import InMemoryIdempotencyStore, RedisIdempotencyStore
from app.integrations.retailer_client import RetailerClient
from app.observability import AuditTrail, MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_config import (
    InMemoryModelSelectionStore,
    RedisModelSelectionStore,
)
from app.orchestrator.model_router import ModelRouter
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.rag.embedding_service import EmbeddingService
from app.rag.retrieval_cache import build_rag_cache
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.sessions import InMemorySessionStore, RedisSessionStore
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry
from app.usage import InMemoryUsageStore, RedisUsageStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_seconds)
    )
    app.state.http_client = http_client

    vector_store = VectorStore(settings)
    app.state.vector_store = vector_store
    try:
        await vector_store.ensure_collection()
    except Exception:
        logger.warning(
            "Qdrant unavailable at startup (%s); chat continues without RAG",
            settings.qdrant_url,
            exc_info=True,
        )

    redis_client = None
    if settings.redis_url:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
    elif settings.environment == "production":
        logger.warning(
            "AI_REDIS_URL is not set; model selection, usage counters, "
            "sessions, idempotency, confirmations, and FAQ RAG cache will "
            "not survive restarts or multi-instance deploys"
        )
    app.state.redis = redis_client

    metrics = MetricsRegistry()
    app.state.metrics = metrics

    audit_trail = (
        AuditTrail(settings.audit_trail_path)
        if settings.audit_trail_path
        else None
    )
    app.state.audit_trail = audit_trail

    model_selection_store = (
        RedisModelSelectionStore(redis_client)
        if redis_client is not None
        else InMemoryModelSelectionStore()
    )
    app.state.model_selection_store = model_selection_store

    usage_store = (
        RedisUsageStore(redis_client)
        if redis_client is not None
        else InMemoryUsageStore()
    )
    app.state.usage_store = usage_store

    retailer = RetailerClient(http_client, settings.retailer_service_url)
    tool_registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        handler = READ_TOOL_HANDLERS[definition.name]
        tool_registry.register(definition, handler)
    for definition in WRITE_TOOL_DEFINITIONS:
        handler = WRITE_TOOL_HANDLERS[definition.name]
        tool_registry.register(definition, handler)
    for definition in SENSITIVE_TOOL_DEFINITIONS:
        handler = SENSITIVE_TOOL_HANDLERS[definition.name]
        tool_registry.register(definition, handler)

    idempotency_store = (
        RedisIdempotencyStore(
            redis_client, ttl_seconds=settings.idempotency_ttl_seconds
        )
        if redis_client is not None
        else InMemoryIdempotencyStore(
            ttl_seconds=settings.idempotency_ttl_seconds
        )
    )
    confirmation_store = (
        RedisConfirmationStore(
            redis_client, ttl_seconds=settings.confirmation_ttl_seconds
        )
        if redis_client is not None
        else InMemoryConfirmationStore(
            ttl_seconds=settings.confirmation_ttl_seconds
        )
    )
    tool_executor = ToolExecutor(
        registry=tool_registry,
        retailer=retailer,
        idempotency_store=idempotency_store,
        audit_trail=audit_trail,
        metrics=metrics,
    )

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

    gateway = AiGateway(
        model_router,
        selection_store=model_selection_store,
        metrics=metrics,
    )
    app.state.model_router = model_router
    app.state.ai_gateway = gateway
    app.state.tool_registry = tool_registry
    app.state.retailer_client = retailer
    app.state.tool_executor = tool_executor
    app.state.idempotency_store = idempotency_store
    app.state.confirmation_store = confirmation_store
    session_store = (
        RedisSessionStore(
            redis_client,
            ttl_seconds=settings.session_ttl_seconds,
            max_turns=settings.session_max_turns,
            history_max_tokens=settings.session_history_max_tokens,
        )
        if redis_client is not None
        else InMemorySessionStore(
            ttl_seconds=settings.session_ttl_seconds,
            max_turns=settings.session_max_turns,
            history_max_tokens=settings.session_history_max_tokens,
        )
    )
    app.state.session_store = session_store
    rag_cache = build_rag_cache(
        redis_client, ttl_seconds=settings.rag_cache_ttl_seconds
    )
    app.state.rag_cache = rag_cache
    retriever = Retriever(
        settings,
        EmbeddingService(settings, http_client),
        vector_store,
        cache=rag_cache,
    )
    app.state.retriever = retriever
    app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=tool_registry,
        settings=settings,
        tool_executor=tool_executor,
        retriever=retriever,
        rag_cache=rag_cache,
        session_store=session_store,
        confirmation_store=confirmation_store,
        usage_store=usage_store,
        metrics=metrics,
    )

    logger.info("AI service started")
    try:
        yield
    finally:
        if audit_trail is not None:
            audit_trail.close()
        if redis_client is not None:
            await redis_client.aclose()
        await vector_store.close()
        await http_client.aclose()
        logger.info("AI service stopped")
