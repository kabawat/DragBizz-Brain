"""Phase 7 — runtime model selection stores + gateway resolution."""

from __future__ import annotations

import asyncio

import pytest

from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.model_config import (
    InMemoryModelSelectionStore,
    ModelSelection,
    RedisModelSelectionStore,
)
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse

SELECTION = ModelSelection(
    provider="fake",
    model="gpt-4o",
    updated_by="admin-1",
    updated_at="2026-07-30T00:00:00+00:00",
)


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str) -> None:
        self.kv[key] = value


class BrokenRedis:
    async def get(self, key: str) -> str:
        raise ConnectionError("redis down")

    async def set(self, key: str, value: str) -> None:
        raise ConnectionError("redis down")


class RecordingProvider(ModelProvider):
    def __init__(self, name: str = "fake") -> None:
        self._name = name
        self.last_request: GenerationRequest | None = None

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.last_request = request
        return GenerationResponse(
            provider=self._name, model=request.model or "default", content="ok"
        )


def _request() -> GenerationRequest:
    return GenerationRequest(messages=[ChatMessage(role="user", content="hi")])


def test_in_memory_store_roundtrip() -> None:
    store = InMemoryModelSelectionStore()
    assert asyncio.run(store.get()) is None
    asyncio.run(store.set(SELECTION))
    assert asyncio.run(store.get()) == SELECTION


def test_redis_store_roundtrip() -> None:
    store = RedisModelSelectionStore(FakeRedis())
    assert asyncio.run(store.get()) is None
    asyncio.run(store.set(SELECTION))
    assert asyncio.run(store.get()) == SELECTION


def test_redis_store_ignores_corrupt_value() -> None:
    redis = FakeRedis()
    redis.kv["ai:model_selection"] = "{not json"
    assert asyncio.run(RedisModelSelectionStore(redis).get()) is None


def test_redis_store_read_fails_open_write_raises() -> None:
    store = RedisModelSelectionStore(BrokenRedis())
    assert asyncio.run(store.get()) is None
    with pytest.raises(ConnectionError):
        asyncio.run(store.set(SELECTION))


def test_gateway_applies_selected_model() -> None:
    provider = RecordingProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    store = InMemoryModelSelectionStore()
    asyncio.run(store.set(SELECTION))
    gateway = AiGateway(router, selection_store=store)

    asyncio.run(gateway.generate(_request()))
    assert provider.last_request is not None
    assert provider.last_request.model == "gpt-4o"


def test_gateway_falls_back_when_selected_provider_missing() -> None:
    provider = RecordingProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    store = InMemoryModelSelectionStore()
    asyncio.run(
        store.set(
            ModelSelection(
                provider="gone",
                model="gpt-4o",
                updated_by="admin-1",
                updated_at="2026-07-30T00:00:00+00:00",
            )
        )
    )
    gateway = AiGateway(router, selection_store=store)

    asyncio.run(gateway.generate(_request()))
    assert provider.last_request is not None
    assert provider.last_request.model is None
