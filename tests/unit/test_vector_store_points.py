from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.rag.chunker import DocumentChunk
from app.rag.vector_store import VectorStore


def _settings() -> Settings:
    return Settings(
        environment="test",
        qdrant_collection="dragbizz_docs",
        embedding_dimensions=2,
    )


def _chunk(chunk_id: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        content="text",
        metadata={"module": "invoice", "source": "invoice/lifecycle.md"},
    )


def test_upsert_chunks_builds_points_with_payload() -> None:
    client = MagicMock()
    client.upsert = AsyncMock()
    store = VectorStore(_settings(), client=client)
    chunk = _chunk("11111111-1111-1111-1111-111111111111")

    asyncio.run(store.upsert_chunks([chunk], [[0.1, 0.2]]))

    kwargs: dict[str, Any] = client.upsert.await_args.kwargs
    assert kwargs["collection_name"] == "dragbizz_docs"
    point = kwargs["points"][0]
    assert point.id == chunk.id
    assert point.vector == [0.1, 0.2]
    assert point.payload == {
        "text": "text",
        "module": "invoice",
        "source": "invoice/lifecycle.md",
    }


def test_upsert_chunks_rejects_length_mismatch() -> None:
    client = MagicMock()
    client.upsert = AsyncMock()
    store = VectorStore(_settings(), client=client)

    with pytest.raises(ValueError):
        asyncio.run(store.upsert_chunks([_chunk("a")], []))
    client.upsert.assert_not_awaited()


def test_upsert_chunks_noop_on_empty() -> None:
    client = MagicMock()
    client.upsert = AsyncMock()
    store = VectorStore(_settings(), client=client)

    asyncio.run(store.upsert_chunks([], []))

    client.upsert.assert_not_awaited()


def test_list_point_ids_paginates_scroll() -> None:
    client = MagicMock()
    client.scroll = AsyncMock(
        side_effect=[
            ([SimpleNamespace(id="a"), SimpleNamespace(id="b")], "cursor-1"),
            ([SimpleNamespace(id="c")], None),
        ]
    )
    store = VectorStore(_settings(), client=client)

    ids = asyncio.run(store.list_point_ids())

    assert ids == {"a", "b", "c"}
    assert client.scroll.await_count == 2


def test_search_maps_query_points_args_and_returns_points() -> None:
    hits = [SimpleNamespace(id="a", score=0.9, payload={"text": "t"})]
    client = MagicMock()
    client.query_points = AsyncMock(return_value=SimpleNamespace(points=hits))
    store = VectorStore(_settings(), client=client)

    result = asyncio.run(
        store.search([0.1, 0.2], limit=5, score_threshold=0.3)
    )

    assert result == hits
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["collection_name"] == "dragbizz_docs"
    assert kwargs["query"] == [0.1, 0.2]
    assert kwargs["limit"] == 5
    assert kwargs["score_threshold"] == 0.3
    assert kwargs["with_payload"] is True


def test_delete_points_noop_on_empty() -> None:
    client = MagicMock()
    client.delete = AsyncMock()
    store = VectorStore(_settings(), client=client)

    asyncio.run(store.delete_points([]))

    client.delete.assert_not_awaited()


def test_delete_points_passes_ids() -> None:
    client = MagicMock()
    client.delete = AsyncMock()
    store = VectorStore(_settings(), client=client)

    asyncio.run(store.delete_points(["a", "b"]))

    kwargs = client.delete.await_args.kwargs
    assert kwargs["collection_name"] == "dragbizz_docs"
    assert kwargs["points_selector"].points == ["a", "b"]
