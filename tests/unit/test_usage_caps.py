"""Phase 7 — per-tenant usage counters and daily hard caps."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.observability.metrics import MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.tools.registry import ToolRegistry
from app.usage import InMemoryUsageStore, RedisUsageStore

STORE_ID = "507f1f77bcf86cd799439011"
OTHER_STORE_ID = "507f1f77bcf86cd799439012"


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, int]] = {}
        self.ttls: dict[str, int] = {}

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = bucket.get(field, 0) + int(amount)
        return bucket[field]

    async def hgetall(self, key: str) -> dict[str, str]:
        return {k: str(v) for k, v in self.hashes.get(key, {}).items()}

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl


class BrokenRedis:
    async def hincrby(self, key: str, field: str, amount: int) -> int:
        raise ConnectionError("redis down")

    async def hgetall(self, key: str) -> dict[str, str]:
        raise ConnectionError("redis down")

    async def expire(self, key: str, ttl: int) -> None:
        raise ConnectionError("redis down")


class StaticProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "static"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider="static",
            model="gpt-4o-mini",
            content="ok",
            input_tokens=100,
            output_tokens=50,
        )


def _service(
    settings: Settings,
    usage_store,
    metrics: MetricsRegistry | None = None,
) -> ChatService:
    provider = StaticProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = ToolRegistry()
    return ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=settings,
        tool_executor=ToolExecutor(registry=registry, retailer=MagicMock()),
        usage_store=usage_store,
        metrics=metrics,
    )


def _chat(service: ChatService, store_id: str = STORE_ID):
    return service.handle(
        ChatRequest(
            text="aaj ki sale?", sessionId=f"s-{store_id}", storeId=store_id
        ),
        user={"sub": "u1"},
        request_id="r1",
        store_id=store_id,
        access_token="token",
    )


# --------------------------------------------------------------- usage stores


def test_in_memory_store_accumulates_per_store() -> None:
    store = InMemoryUsageStore()

    async def run() -> None:
        await store.record(
            STORE_ID, input_tokens=100, output_tokens=50, cost_usd=0.001
        )
        await store.record(
            STORE_ID, input_tokens=10, output_tokens=5, cost_usd=0.0005
        )
        usage = await store.get_today(STORE_ID)
        assert usage.requests == 2
        assert usage.input_tokens == 110
        assert usage.output_tokens == 55
        assert usage.total_tokens == 165
        assert usage.cost_usd == pytest.approx(0.0015)
        other = await store.get_today(OTHER_STORE_ID)
        assert other.requests == 0

    asyncio.run(run())


def test_redis_store_accumulates_and_expires() -> None:
    redis = FakeRedis()
    store = RedisUsageStore(redis)

    async def run() -> None:
        await store.record(
            STORE_ID, input_tokens=100, output_tokens=50, cost_usd=0.001
        )
        usage = await store.get_today(STORE_ID)
        assert usage.requests == 1
        assert usage.total_tokens == 150
        assert usage.cost_usd == pytest.approx(0.001)

    asyncio.run(run())
    assert redis.ttls  # counters expire instead of accumulating forever


def test_redis_store_fails_open_on_outage() -> None:
    store = RedisUsageStore(BrokenRedis())

    async def run() -> None:
        await store.record(
            STORE_ID, input_tokens=1, output_tokens=1, cost_usd=0.0
        )
        usage = await store.get_today(STORE_ID)
        assert usage.total_tokens == 0

    asyncio.run(run())


# ----------------------------------------------------------------- hard caps


def test_chat_records_usage() -> None:
    usage_store = InMemoryUsageStore()
    service = _service(Settings(environment="test"), usage_store)
    asyncio.run(_chat(service))

    usage = asyncio.run(usage_store.get_today(STORE_ID))
    assert usage.requests == 1
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    # 100 * 0.15/1M + 50 * 0.60/1M
    assert usage.cost_usd == pytest.approx(0.000045)


def test_chat_blocked_when_token_cap_reached() -> None:
    usage_store = InMemoryUsageStore()
    metrics = MetricsRegistry()
    settings = Settings(environment="test", tenant_daily_token_cap=200)
    service = _service(settings, usage_store, metrics)

    asyncio.run(_chat(service))  # 150 tokens — under cap
    asyncio.run(_chat(service))  # 300 tokens — reaches cap
    with pytest.raises(AppError) as exc_info:
        asyncio.run(_chat(service))
    assert exc_info.value.code == "AI_USAGE_CAP_EXCEEDED"
    assert exc_info.value.status_code == 429
    assert metrics.snapshot()["chat"]["capBlocked"] == 1

    # Cap is per store — another tenant is unaffected.
    response = asyncio.run(_chat(service, store_id=OTHER_STORE_ID))
    assert response.message == "ok"


def test_chat_blocked_when_cost_cap_reached() -> None:
    usage_store = InMemoryUsageStore()
    settings = Settings(environment="test", tenant_daily_cost_cap_usd=0.00004)
    service = _service(settings, usage_store)

    asyncio.run(_chat(service))
    with pytest.raises(AppError) as exc_info:
        asyncio.run(_chat(service))
    assert exc_info.value.code == "AI_USAGE_CAP_EXCEEDED"


def test_chat_unlimited_when_caps_disabled() -> None:
    service = _service(Settings(environment="test"), InMemoryUsageStore())
    for _ in range(3):
        response = asyncio.run(_chat(service))
        assert response.message == "ok"
