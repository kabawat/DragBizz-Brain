from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.observability.pricing import PricingConfig, pricing_from_settings
from app.rag.chunker import DocumentChunk, chunk_markdown, estimate_tokens
from app.rag.corpus import knowledge_corpus_version
from app.rag.embedding_service import EmbeddingService
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "knowledge"


@dataclass(frozen=True)
class IndexSummary:
    files_scanned: int
    chunks_total: int
    chunks_embedded: int
    chunks_skipped: int
    points_deleted: int
    embedded_tokens: int
    estimated_cost_usd: float
    usage_source: str
    cost_source: str
    pricing_version: str
    corpus_version: str


async def index_knowledge(
    root: Path,
    embedding_service: EmbeddingService,
    vector_store: VectorStore,
    *,
    pricing: PricingConfig | None = None,
) -> IndexSummary:
    """Sync `root` markdown docs into Qdrant.

    Deterministic chunk IDs make this incremental: only chunks whose ID is
    not already in the collection get embedded; points whose ID no longer
    maps to any current chunk are deleted.
    """
    files = sorted(root.rglob("*.md"))
    corpus_version = knowledge_corpus_version(root)
    desired: dict[str, DocumentChunk] = {}
    for path in files:
        source = str(path.relative_to(root))
        for chunk in chunk_markdown(path.read_text(encoding="utf-8"), source=source):
            desired[chunk.id] = chunk.model_copy(
                update={
                    "metadata": {
                        **chunk.metadata,
                        "corpus_version": corpus_version,
                    }
                }
            )

    existing_ids = await vector_store.list_point_ids()
    new_chunks = [c for cid, c in desired.items() if cid not in existing_ids]
    stale_ids = sorted(existing_ids - desired.keys())

    if new_chunks:
        vectors = await embedding_service.embed([c.content for c in new_chunks])
        await vector_store.upsert_chunks(new_chunks, vectors)
    if stale_ids:
        await vector_store.delete_points(stale_ids)
    await vector_store.update_corpus_version(
        existing_ids - set(stale_ids), corpus_version=corpus_version
    )

    embedded_tokens = sum(estimate_tokens(c.content) for c in new_chunks)
    pricing_cfg = pricing or pricing_from_settings(get_settings())
    cost = pricing_cfg.estimate_embedding_cost(embedded_tokens)
    summary = IndexSummary(
        files_scanned=len(files),
        chunks_total=len(desired),
        chunks_embedded=len(new_chunks),
        chunks_skipped=len(desired) - len(new_chunks),
        points_deleted=len(stale_ids),
        embedded_tokens=embedded_tokens,
        estimated_cost_usd=cost.cost_usd or 0.0,
        usage_source=cost.usage_source,
        cost_source=cost.cost_source,
        pricing_version=cost.pricing_version,
        corpus_version=corpus_version,
    )
    logger.info(
        "Index summary: files=%s chunks=%s embedded=%s skipped=%s deleted=%s "
        "tokens=%s cost_usd=%.6f usage_source=%s cost_source=%s "
        "pricing_version=%s",
        summary.files_scanned,
        summary.chunks_total,
        summary.chunks_embedded,
        summary.chunks_skipped,
        summary.points_deleted,
        summary.embedded_tokens,
        summary.estimated_cost_usd,
        summary.usage_source,
        summary.cost_source,
        summary.pricing_version,
    )
    return summary


async def _run_cli(settings: Settings, root: Path) -> IndexSummary:
    vector_store = VectorStore(settings)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.chat.provider_timeout_seconds)
    ) as http_client:
        try:
            await vector_store.ensure_collection()
            return await index_knowledge(
                root,
                EmbeddingService(settings, http_client),
                vector_store,
                pricing=pricing_from_settings(settings),
            )
        finally:
            await vector_store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag.indexer",
        description="Index knowledge/ markdown docs into Qdrant",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_KNOWLEDGE_ROOT,
        help="Knowledge docs root (default: dragbizz-ai/knowledge)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required in production to confirm indexing the live collection",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()

    if settings.server.environment == "production" and not args.yes:
        logger.error(
            "Refusing to index production collection %s without --yes",
            settings.rag.collection,
        )
        return 1
    if not args.root.is_dir():
        logger.error("Knowledge root not found: %s", args.root)
        return 1

    logger.info(
        "Indexing %s -> %s (%s)",
        args.root,
        settings.rag.collection,
        settings.rag.qdrant_url,
    )
    started = time.perf_counter()
    try:
        asyncio.run(_run_cli(settings, args.root))
    except Exception:
        # Alertable marker: cron/CI should page on "Index run FAILED" or on
        # the non-zero exit code.
        logger.exception(
            "Index run FAILED after %.1fs (collection=%s)",
            time.perf_counter() - started,
            settings.rag.collection,
        )
        return 1
    logger.info(
        "Index run completed in %.1fs (collection=%s)",
        time.perf_counter() - started,
        settings.rag.collection,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
