from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.rag.embedding_service import EMBEDDING_BATCH_SIZE, EmbeddingService


def _settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "environment": "test",
        "openai_api_key": "test-key",
        "openai_base_url": "https://api.openai.com/v1",
        "embedding_model": "text-embedding-3-small",
        "provider_timeout_seconds": 5.0,
    }
    data.update(overrides)
    return Settings(**data)


def _embedding_response(inputs: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {"index": i, "embedding": [float(i), 0.5]}
                for i in range(len(inputs))
            ]
        },
    )


def test_embed_returns_vectors_in_input_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        payload = json.loads(request.content)
        assert payload["model"] == "text-embedding-3-small"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [1.0]},
                    {"index": 0, "embedding": [0.0]},
                ]
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            vectors = await service.embed(["a", "b"])
        assert vectors == [[0.0], [1.0]]

    asyncio.run(run())


def test_embed_batches_large_inputs() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        batch_sizes.append(len(inputs))
        return _embedding_response(inputs)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            texts = [f"text {i}" for i in range(EMBEDDING_BATCH_SIZE + 7)]
            vectors = await service.embed(texts)
        assert len(vectors) == EMBEDDING_BATCH_SIZE + 7
        assert batch_sizes == [EMBEDDING_BATCH_SIZE, 7]

    asyncio.run(run())


def test_embed_empty_input_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            assert await service.embed([]) == []

    asyncio.run(run())


def test_embed_requires_api_key() -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            service = EmbeddingService(_settings(openai_api_key=None), client)
            with pytest.raises(AppError) as exc_info:
                await service.embed(["a"])
        assert exc_info.value.code == "AI_PROVIDER_NOT_CONFIGURED"
        assert exc_info.value.status_code == 503

    asyncio.run(run())


def test_embed_maps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            with pytest.raises(AppError) as exc_info:
                await service.embed(["a"])
        assert exc_info.value.code == "AI_PROVIDER_ERROR"
        assert exc_info.value.status_code == 502

    asyncio.run(run())


def test_embed_rejects_unexpected_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0}]})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            with pytest.raises(AppError) as exc_info:
                await service.embed(["a"])
        assert exc_info.value.code == "AI_PROVIDER_ERROR"

    asyncio.run(run())


def test_embed_rejects_count_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1]}]}
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            with pytest.raises(AppError) as exc_info:
                await service.embed(["a", "b"])
        assert exc_info.value.code == "AI_PROVIDER_ERROR"

    asyncio.run(run())


def test_embed_one_returns_single_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _embedding_response(json.loads(request.content)["input"])

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = EmbeddingService(_settings(), client)
            vector = await service.embed_one("hello")
        assert vector == [0.0, 0.5]

    asyncio.run(run())
