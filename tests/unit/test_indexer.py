from __future__ import annotations

import asyncio
from pathlib import Path

from app.rag.chunker import DocumentChunk
from app.rag.indexer import index_knowledge

DOC_A = """---
module: invoice
feature: lifecycle
---

# Invoice Lifecycle

## Overview

Invoices move from draft to released.
"""

DOC_B = """---
module: customer
feature: khata
---

# Khata

## Overview

You Gave and You Got entries build a running balance.
"""


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [[0.1, 0.2] for _ in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: dict[str, DocumentChunk] = {}
        self.deleted: list[str] = []

    async def list_point_ids(self) -> set[str]:
        return set(self.points)

    async def upsert_chunks(
        self, chunks: list[DocumentChunk], vectors: list[list[float]]
    ) -> None:
        assert len(chunks) == len(vectors)
        for chunk in chunks:
            self.points[chunk.id] = chunk

    async def delete_points(self, ids: list[str]) -> None:
        self.deleted.extend(ids)
        for point_id in ids:
            self.points.pop(point_id, None)


def _write_docs(root: Path, docs: dict[str, str]) -> None:
    for relative, text in docs.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_indexer_embeds_and_upserts_all_chunks_first_run(tmp_path: Path) -> None:
    _write_docs(tmp_path, {"invoice/lifecycle.md": DOC_A, "customer/khata.md": DOC_B})
    embeddings = FakeEmbeddingService()
    store = FakeVectorStore()

    summary = asyncio.run(index_knowledge(tmp_path, embeddings, store))

    assert summary.files_scanned == 2
    assert summary.chunks_total == 2
    assert summary.chunks_embedded == 2
    assert summary.chunks_skipped == 0
    assert summary.points_deleted == 0
    assert summary.embedded_tokens > 0
    assert summary.estimated_cost_usd > 0
    assert len(store.points) == 2
    payload_meta = next(iter(store.points.values())).metadata
    assert payload_meta["module"] in {"invoice", "customer"}


def test_indexer_rerun_is_idempotent(tmp_path: Path) -> None:
    _write_docs(tmp_path, {"invoice/lifecycle.md": DOC_A})
    embeddings = FakeEmbeddingService()
    store = FakeVectorStore()

    first = asyncio.run(index_knowledge(tmp_path, embeddings, store))
    second = asyncio.run(index_knowledge(tmp_path, embeddings, store))

    assert first.chunks_embedded == 1
    assert second.chunks_embedded == 0
    assert second.chunks_skipped == 1
    assert second.points_deleted == 0
    assert len(embeddings.embedded) == 1
    assert len(store.points) == 1


def test_indexer_reembeds_only_changed_doc(tmp_path: Path) -> None:
    _write_docs(tmp_path, {"invoice/lifecycle.md": DOC_A, "customer/khata.md": DOC_B})
    embeddings = FakeEmbeddingService()
    store = FakeVectorStore()
    asyncio.run(index_knowledge(tmp_path, embeddings, store))

    _write_docs(
        tmp_path,
        {"invoice/lifecycle.md": DOC_A.replace("draft to released", "draft to final")},
    )
    summary = asyncio.run(index_knowledge(tmp_path, embeddings, store))

    assert summary.chunks_embedded == 1
    assert summary.chunks_skipped == 1
    assert summary.points_deleted == 1  # old version of the changed chunk
    assert len(store.points) == 2


def test_indexer_deletes_points_for_removed_docs(tmp_path: Path) -> None:
    _write_docs(tmp_path, {"invoice/lifecycle.md": DOC_A, "customer/khata.md": DOC_B})
    embeddings = FakeEmbeddingService()
    store = FakeVectorStore()
    asyncio.run(index_knowledge(tmp_path, embeddings, store))

    (tmp_path / "customer/khata.md").unlink()
    summary = asyncio.run(index_knowledge(tmp_path, embeddings, store))

    assert summary.files_scanned == 1
    assert summary.chunks_embedded == 0
    assert summary.points_deleted == 1
    assert len(store.points) == 1
    remaining = next(iter(store.points.values()))
    assert remaining.metadata["module"] == "invoice"


def test_indexer_empty_root_clears_collection(tmp_path: Path) -> None:
    embeddings = FakeEmbeddingService()
    store = FakeVectorStore()
    store.points["11111111-1111-1111-1111-111111111111"] = DocumentChunk(
        id="11111111-1111-1111-1111-111111111111",
        content="orphan",
        metadata={"source": "gone.md"},
    )

    summary = asyncio.run(index_knowledge(tmp_path, embeddings, store))

    assert summary.chunks_total == 0
    assert summary.points_deleted == 1
    assert store.points == {}
