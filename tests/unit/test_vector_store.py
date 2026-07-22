from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.rag.vector_store import VectorStore


def _settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "environment": "test",
        "qdrant_url": "http://localhost:6333",
        "qdrant_api_key": None,
        "qdrant_collection": "dragbizz_docs",
        "embedding_dimensions": 1536,
        "request_timeout_seconds": 10.0,
    }
    data.update(overrides)
    return Settings(**data)


def test_ensure_collection_creates_when_missing() -> None:
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=False)
    client.create_collection = AsyncMock()
    client.close = AsyncMock()

    async def run() -> None:
        store = VectorStore(_settings(), client=client)
        await store.ensure_collection()

    asyncio.run(run())

    client.collection_exists.assert_awaited_once_with("dragbizz_docs")
    client.create_collection.assert_awaited_once()
    kwargs = client.create_collection.await_args.kwargs
    assert kwargs["collection_name"] == "dragbizz_docs"
    assert kwargs["vectors_config"].size == 1536


def test_ensure_collection_skips_when_present() -> None:
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.create_collection = AsyncMock()

    async def run() -> None:
        store = VectorStore(_settings(), client=client)
        await store.ensure_collection()

    asyncio.run(run())

    client.collection_exists.assert_awaited_once_with("dragbizz_docs")
    client.create_collection.assert_not_awaited()


def test_ensure_collection_falls_back_to_get_collections() -> None:
    client = MagicMock(spec=["get_collections", "create_collection", "close"])
    client.get_collections = AsyncMock(
        return_value=SimpleNamespace(collections=[SimpleNamespace(name="other")])
    )
    client.create_collection = AsyncMock()

    async def run() -> None:
        store = VectorStore(_settings(), client=client)
        await store.ensure_collection()

    asyncio.run(run())

    client.get_collections.assert_awaited_once()
    client.create_collection.assert_awaited_once()


def test_ping_returns_false_on_error() -> None:
    client = MagicMock()
    client.get_collections = AsyncMock(side_effect=ConnectionError("down"))

    async def run() -> None:
        store = VectorStore(_settings(), client=client)
        assert await store.ping() is False
        assert await store.is_ready() is False

    asyncio.run(run())


def test_ping_returns_true_when_reachable() -> None:
    client = MagicMock()
    client.get_collections = AsyncMock(
        return_value=SimpleNamespace(collections=[])
    )

    async def run() -> None:
        store = VectorStore(_settings(), client=client)
        assert await store.ping() is True

    asyncio.run(run())
