from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.rag.retriever import Retriever


def _settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "environment": "test",
        "rag_top_k": 5,
        "rag_score_threshold": 0.3,
    }
    data.update(overrides)
    return Settings(**data)


def _point(score: float, text: str, **metadata: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"id-{score}", score=score, payload={"text": text, **metadata}
    )


def _retriever(
    points: list[SimpleNamespace] | Exception,
    settings: Settings | None = None,
) -> tuple[Retriever, MagicMock, MagicMock]:
    embeddings = MagicMock()
    embeddings.embed_one = AsyncMock(return_value=[0.1, 0.2])
    store = MagicMock()
    if isinstance(points, Exception):
        store.search = AsyncMock(side_effect=points)
    else:
        store.search = AsyncMock(return_value=points)
    return Retriever(settings or _settings(), embeddings, store), embeddings, store


def test_retrieve_preserves_ranking_and_maps_payload() -> None:
    points = [
        _point(0.91, "POS checkout flow", module="invoice", source="invoice/pos.md"),
        _point(0.72, "Khata balance", module="customer", source="customer/khata.md"),
    ]
    retriever, embeddings, store = _retriever(points)

    chunks = asyncio.run(retriever.retrieve("how does POS work?"))

    embeddings.embed_one.assert_awaited_once_with("how does POS work?")
    assert [c.score for c in chunks] == [0.91, 0.72]
    assert chunks[0].text == "POS checkout flow"
    assert chunks[0].metadata == {"module": "invoice", "source": "invoice/pos.md"}
    assert "text" not in chunks[0].metadata


def test_retrieve_passes_configured_limit_and_threshold() -> None:
    settings = _settings(rag_top_k=3, rag_score_threshold=0.55)
    retriever, _, store = _retriever([], settings)

    asyncio.run(retriever.retrieve("q"))

    kwargs = store.search.await_args.kwargs
    assert store.search.await_args.args == ([0.1, 0.2],)
    assert kwargs == {"limit": 3, "score_threshold": 0.55}


def test_retrieve_returns_empty_when_qdrant_down(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retriever, _, _ = _retriever(ConnectionError("qdrant down"))

    with caplog.at_level(logging.WARNING):
        chunks = asyncio.run(retriever.retrieve("q"))

    assert chunks == []
    assert any("without RAG context" in r.message for r in caplog.records)


def test_retrieve_skips_points_without_text() -> None:
    points = [
        SimpleNamespace(id="empty", score=0.9, payload={"module": "invoice"}),
        _point(0.8, "valid text", module="gst"),
    ]
    retriever, _, _ = _retriever(points)

    chunks = asyncio.run(retriever.retrieve("q"))

    assert len(chunks) == 1
    assert chunks[0].text == "valid text"


def test_retrieve_propagates_embedding_errors() -> None:
    retriever, embeddings, store = _retriever([])
    embeddings.embed_one = AsyncMock(side_effect=RuntimeError("embed failed"))

    with pytest.raises(RuntimeError):
        asyncio.run(retriever.retrieve("q"))
    store.search.assert_not_awaited()
