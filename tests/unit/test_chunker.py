from __future__ import annotations

from app.rag.chunker import (
    CHUNK_MAX_TOKENS,
    chunk_markdown,
    estimate_tokens,
)

DOC = """---
module: invoice
feature: lifecycle
version: 1
language: en
status: shipped
---

# Invoice Lifecycle

## Overview

Invoices move from draft to released.

## Errors

Released invoices cannot be edited.
"""


def test_chunker_carries_frontmatter_metadata() -> None:
    chunks = chunk_markdown(DOC, source="invoice/lifecycle.md")

    assert chunks
    for chunk in chunks:
        assert chunk.metadata["module"] == "invoice"
        assert chunk.metadata["feature"] == "lifecycle"
        assert chunk.metadata["status"] == "shipped"
        assert chunk.metadata["source"] == "invoice/lifecycle.md"
        assert chunk.metadata["title"] == "Invoice Lifecycle"


def test_chunker_packs_small_sections_into_one_chunk() -> None:
    chunks = chunk_markdown(DOC, source="invoice/lifecycle.md")

    assert len(chunks) == 1
    assert "draft to released" in chunks[0].content
    assert "cannot be edited" in chunks[0].content
    assert chunks[0].content.startswith("Invoice Lifecycle")


def test_chunker_splits_oversized_sections_with_overlap() -> None:
    paragraphs = [f"Paragraph {i}. " + ("detail " * 60) for i in range(20)]
    doc = "# Big Doc\n\n## Huge\n\n" + "\n\n".join(paragraphs)

    chunks = chunk_markdown(doc, source="faq/big.md")

    assert len(chunks) > 1
    for chunk in chunks:
        assert estimate_tokens(chunk.content) <= CHUNK_MAX_TOKENS + 50
        assert chunk.metadata["heading"] == "Huge"

    first_paragraphs = set(chunks[0].content.split("\n\n"))
    second_paragraphs = set(chunks[1].content.split("\n\n"))
    assert first_paragraphs & second_paragraphs, "expected overlap between chunks"


def test_chunker_ids_are_deterministic_and_content_sensitive() -> None:
    first = chunk_markdown(DOC, source="invoice/lifecycle.md")
    second = chunk_markdown(DOC, source="invoice/lifecycle.md")
    changed = chunk_markdown(
        DOC.replace("draft to released", "draft to final"),
        source="invoice/lifecycle.md",
    )
    moved = chunk_markdown(DOC, source="invoice/other.md")

    assert [c.id for c in first] == [c.id for c in second]
    assert first[0].id != changed[0].id
    assert first[0].id != moved[0].id


def test_chunker_handles_document_without_frontmatter_or_headings() -> None:
    chunks = chunk_markdown("Just a plain paragraph.", source="misc/plain.md")

    assert len(chunks) == 1
    assert chunks[0].content == "Just a plain paragraph."
    assert chunks[0].metadata == {"source": "misc/plain.md"}


def test_chunker_returns_nothing_for_empty_body() -> None:
    assert chunk_markdown("---\nmodule: x\n---\n", source="x/empty.md") == []
