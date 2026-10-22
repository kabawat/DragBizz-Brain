import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.confirmations import InMemoryConfirmationStore, RedisConfirmationStore
from app.events import DeadLetterStore, RedisStreamConsumer
from app.executors.tool_executor import ToolExecutor
from app.guards import PromptAbuseLimiter
from app.idempotency import InMemoryIdempotencyStore, RedisIdempotencyStore
from app.insights import build_insight_cache
from app.integrations.retailer_client import RetailerClient
from app.limits import (
    CircuitBreaker,
    ConcurrencyGate,
    InMemoryConcurrencyGate,
    InMemoryRateLimiter,
    RateLimiter,
)
from app.observability import (
    AuditTrail,
    MetricsRegistry,
    init_middleware_telemetry,
    pricing_from_settings,
    shutdown_middleware_telemetry,
)
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_config import (
    InMemoryModelSelectionStore,
    RedisModelSelectionStore,
)
from app.orchestrator.model_router import ModelRouter
from app.providers.openai_compatible import (
    OPENAI_PROVIDER_NAME,
    OpenAICompatibleProvider,
    build_cheaper_provider,
    build_google_provider,
)
from app.rag.embedding_service import EmbeddingService
from app.rag.retrieval_cache import build_rag_cache
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.sessions import (
    InMemorySessionStore,
    MongoHistoryStore,
    NoOpHistoryStore,
    RedisSessionStore,
    drain_pending_persist_tasks,
)
from app.tools.registry import build_unified_tool_registry
from app.usage import InMemoryUsageStore, RedisUsageStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    telemetry_providers = init_middleware_telemetry(settings)
    app.state.telemetry_providers = telemetry_providers

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.services.request_timeout_seconds),
        limits=httpx.Limits(
            max_keepalive_connections=20,
            max_connections=50,
            keepalive_expiry=30.0,
        ),
    )
    app.state.http_client = http_client

    vector_store = VectorStore(settings)
    app.state.vector_store = vector_store
    try:
        await vector_store.ensure_collection()
    except Exception:
        logger.warning(
            "Qdrant unavailable at startup (%s); chat continues without RAG",
            settings.rag.qdrant_url,
            exc_info=True,
        )

    redis_client = None
    if settings.limits.redis_url:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(
            settings.limits.redis_url, decode_responses=True
        )
        try:
            await redis_client.ping()
        except Exception as exc:
            await redis_client.aclose()
            raise RuntimeError(
                "AI_REDIS_URL is set but Redis is unreachable; "
                "refusing to start without shared safety controls"
            ) from exc
    elif settings.server.environment == "production":
        # Settings validator should already catch this; belt-and-suspenders.
        raise RuntimeError("AI_REDIS_URL is required in production")
    app.state.redis = redis_client

    metrics = MetricsRegistry()
    app.state.metrics = metrics

    audit_trail = (
        AuditTrail(settings.limits.audit_trail_path)
        if settings.limits.audit_trail_path
        else None
    )
    app.state.audit_trail = audit_trail

    limits = settings.limits
    if redis_client is not None:
        rate_limiter: RateLimiter | InMemoryRateLimiter = RateLimiter(
            redis_client,
            chat_per_minute=limits.chat_rate_per_minute,
            confirm_per_minute=limits.confirm_rate_per_minute,
        )
        concurrency_gate: ConcurrencyGate | InMemoryConcurrencyGate = ConcurrencyGate(
            redis_client,
            max_chat=limits.max_concurrent_chats,
            max_confirm=limits.max_concurrent_confirms,
            lease_seconds=limits.concurrency_lease_seconds,
        )
    else:
        rate_limiter = InMemoryRateLimiter(
            chat_per_minute=limits.chat_rate_per_minute,
            confirm_per_minute=limits.confirm_rate_per_minute,
        )
        concurrency_gate = InMemoryConcurrencyGate(
            max_chat=limits.max_concurrent_chats,
            max_confirm=limits.max_concurrent_confirms,
            lease_seconds=limits.concurrency_lease_seconds,
        )
    app.state.rate_limiter = rate_limiter
    app.state.concurrency_gate = concurrency_gate

    provider_breaker = CircuitBreaker(
        name="provider",
        failure_threshold=limits.breaker_failure_threshold,
        cooldown_seconds=limits.breaker_cooldown_seconds,
        metrics=metrics,
    )
    app.state.provider_breaker = provider_breaker

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

    retailer = RetailerClient(http_client, settings.services.retailer_url)
    tool_registry = build_unified_tool_registry()

    idempotency_store = (
        RedisIdempotencyStore(
            redis_client, ttl_seconds=settings.session.idempotency_ttl_seconds
        )
        if redis_client is not None
        else InMemoryIdempotencyStore(
            ttl_seconds=settings.session.idempotency_ttl_seconds
        )
    )
    confirmation_store = (
        RedisConfirmationStore(
            redis_client, ttl_seconds=settings.session.confirmation_ttl_seconds
        )
        if redis_client is not None
        else InMemoryConfirmationStore(
            ttl_seconds=settings.session.confirmation_ttl_seconds
        )
    )
    insight_cache = build_insight_cache(redis_client, ttl_seconds=900)
    app.state.insight_cache = insight_cache
    tool_executor = ToolExecutor(
        registry=tool_registry,
        retailer=retailer,
        idempotency_store=idempotency_store,
        audit_trail=audit_trail,
        metrics=metrics,
        insight_cache=insight_cache,
    )

    model_router = ModelRouter()
    if settings.openai.api_key:
        model_router.register(OpenAICompatibleProvider(settings, http_client))
    else:
        logger.warning("AI_OPENAI_API_KEY is not set; OpenAI provider unavailable")
    google = build_google_provider(settings, http_client)
    if google is not None:
        model_router.register(google)
    cheaper = build_cheaper_provider(settings, http_client)
    if cheaper is not None:
        model_router.register(cheaper)
    if model_router.available_providers():
        if model_router.get(settings.active_provider) is not None:
            model_router.set_active(settings.active_provider)
        elif model_router.get(OPENAI_PROVIDER_NAME) is not None:
            model_router.set_active(OPENAI_PROVIDER_NAME)
        else:
            model_router.set_active(model_router.available_providers()[0])
        if (
            settings.active_provider
            and model_router.get(settings.active_provider) is None
        ):
            logger.warning(
                "Active provider '%s' is not registered",
                settings.active_provider,
            )
    else:
        logger.warning("No chat provider is configured")

    gateway = AiGateway(
        model_router,
        selection_store=model_selection_store,
        metrics=metrics,
        breaker=provider_breaker,
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
            ttl_seconds=settings.session.ttl_seconds,
            max_turns=settings.session.max_turns,
            history_max_tokens=settings.session.history_max_tokens,
        )
        if redis_client is not None
        else InMemorySessionStore(
            ttl_seconds=settings.session.ttl_seconds,
            max_turns=settings.session.max_turns,
            history_max_tokens=settings.session.history_max_tokens,
        )
    )
    app.state.session_store = session_store

    mongo_client = None
    history_store = NoOpHistoryStore()
    if settings.session.mongodb_uri:
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo_client = AsyncIOMotorClient(settings.session.mongodb_uri)
        try:
            await mongo_client.admin.command("ping")
            history_store = MongoHistoryStore(mongo_client.get_default_database())
            await history_store.ensure_indexes()
            logger.info("Durable chat history Mongo connected")
        except Exception:
            logger.warning(
                "AI_MONGODB_URI set but Mongo unreachable; history fail-open",
                exc_info=True,
            )
            mongo_client.close()
            mongo_client = None
            history_store = NoOpHistoryStore()
    app.state.mongo_client = mongo_client
    app.state.history_store = history_store

    rag_cache = build_rag_cache(
        redis_client, ttl_seconds=settings.rag.cache_ttl_seconds
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
        prompt_abuse_limiter=PromptAbuseLimiter(redis_client),
        history_store=history_store,
        confirmation_store=confirmation_store,
        usage_store=usage_store,
        metrics=metrics,
        audit_trail=audit_trail,
        pricing=pricing_from_settings(settings),
    )

    # Phase 7: Proactive Retail Intelligence
    from app.integrations.core_grpc_client import CoreGrpcClient
    from app.proactive import (
        CoreStoreProvider,
        DailyBriefingScheduler,
        InMemoryAlertDedupStore,
        InMemoryNotificationStore,
        LowStockMonitor,
        MongoNotificationStore,
        RedisAlertDedupStore,
    )

    core_grpc_client = CoreGrpcClient(
        target_address=(
            f"{settings.services.retailer_grpc_host}:"
            f"{settings.services.retailer_intelligence_grpc_port}"
        ),
        timeout=settings.services.request_timeout_seconds,
        root_ca_path=settings.services.retailer_intelligence_grpc_ca_path,
        client_cert_path=settings.services.retailer_intelligence_grpc_cert_path,
        client_key_path=settings.services.retailer_intelligence_grpc_key_path,
    )
    app.state.core_grpc_client = core_grpc_client

    notification_store = (
        MongoNotificationStore(mongo_client.get_default_database())
        if mongo_client is not None
        else InMemoryNotificationStore()
    )
    if isinstance(notification_store, MongoNotificationStore):
        await notification_store.ensure_indexes()
    app.state.notification_store = notification_store

    alert_dedup_store = (
        RedisAlertDedupStore(redis_client)
        if redis_client is not None
        else InMemoryAlertDedupStore()
    )
    app.state.alert_dedup_store = alert_dedup_store

    stock_monitor = LowStockMonitor(
        dedup_store=alert_dedup_store,
        notification_store=notification_store,
        grpc_client=core_grpc_client,
        retailer_client=retailer,
        enabled=settings.proactive.alerts_enabled,
        cooldown_seconds=settings.proactive.low_stock_cooldown_seconds,
        claim_ttl_seconds=settings.proactive.claim_ttl_seconds,
    )
    app.state.stock_monitor = stock_monitor

    briefing_scheduler = DailyBriefingScheduler(
        notification_store=notification_store,
        grpc_client=core_grpc_client,
        retailer_client=retailer,
        redis_client=redis_client,
        enabled=settings.proactive.daily_brief_enabled,
        briefing_time=settings.proactive.daily_brief_time,
        timezone_str=settings.proactive.daily_brief_timezone,
    )
    app.state.briefing_scheduler = briefing_scheduler
    if settings.proactive.daily_brief_enabled:
        await briefing_scheduler.start(
            store_provider=CoreStoreProvider(
                grpc_client=core_grpc_client,
                retailer_client=retailer,
            )
        )

    event_consumer = None
    if redis_client is not None and settings.events.consumer_enabled:
        dead_letter_store = DeadLetterStore(
            mongo_client.get_default_database() if mongo_client is not None else None
        )
        event_consumer = RedisStreamConsumer(
            redis_client=redis_client,
            insight_cache=insight_cache,
            dead_letter_store=dead_letter_store,
            stream_name=settings.events.stream_name,
            group_name=settings.events.consumer_group,
            min_idle_ms=settings.events.consumer_min_idle_ms,
            poll_timeout_ms=settings.events.consumer_poll_timeout_ms,
            max_retries=settings.events.consumer_max_retries,
            batch_size=settings.events.consumer_batch_size,
            stock_monitor=stock_monitor,
        )
        await event_consumer.start()
        app.state.event_consumer = event_consumer
        app.state.dead_letter_store = dead_letter_store

    logger.info("AI service started")
    try:
        yield
    finally:
        if briefing_scheduler is not None:
            await briefing_scheduler.stop()
        if event_consumer is not None:
            await event_consumer.stop()
        await drain_pending_persist_tasks(timeout=5.0)
        if audit_trail is not None:
            audit_trail.close()
        if redis_client is not None:
            await redis_client.aclose()
        if mongo_client is not None:
            mongo_client.close()
        await vector_store.close()
        await http_client.aclose()
        core_grpc_client.close()
        shutdown_middleware_telemetry(telemetry_providers)
        logger.info("AI service stopped")
