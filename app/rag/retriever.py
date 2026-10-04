from __future__ import annotations

import logging

from app.config import Settings
from app.rag.embedding_service import EmbeddingService
from app.rag.models import RetrievedChunk
from app.rag.retrieval_cache import NoOpRagCache, RagCache
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

__all__ = ["RetrievedChunk", "Retriever"]


class Retriever:
    """Question → embedding → top-k relevant chunks from Qdrant.

    Optional short-TTL cache skips embed + search for repeated FAQ questions.
    Single seam for later reranking; Qdrant outage degrades to no context.
    """

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        cache: RagCache | None = None,
    ) -> None:
        self._settings = settings
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._cache: RagCache = cache or NoOpRagCache()

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        top_k = self._settings.rag.top_k
        score_threshold = self._settings.rag.score_threshold
        cached = await self._cache.get_chunks(
            question, top_k=top_k, score_threshold=score_threshold
        )
        if cached is not None:
            return cached

        vector = await self._embedding_service.embed_one(question)
        try:
            points = await self._vector_store.search(
                vector,
                limit=top_k,
                score_threshold=score_threshold,
            )
        except Exception:
            logger.warning(
                "Qdrant search failed; continuing without RAG context",
                exc_info=True,
            )
            return []

        chunks: list[RetrievedChunk] = []
        for point in points:
            payload = dict(point.payload or {})
            text = payload.pop("text", "")
            if not text:
                logger.warning("Skipping point %s without text payload", point.id)
                continue
            chunks.append(
                RetrievedChunk(
                    id=str(point.id),
                    text=text,
                    metadata=payload,
                    score=point.score,
                )
            )
        await self._cache.set_chunks(
            question,
            top_k=top_k,
            score_threshold=score_threshold,
            chunks=chunks,
        )
        return chunks
