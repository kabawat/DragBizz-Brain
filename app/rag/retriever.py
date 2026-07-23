from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import Settings
from app.rag.embedding_service import EmbeddingService
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RetrievedChunk(BaseModel):
    id: str = ""
    text: str
    metadata: dict[str, str]
    score: float


class Retriever:
    """Question → embedding → top-k relevant chunks from Qdrant.

    Single seam for later reranking; Qdrant outage degrades to no context.
    """

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
    ) -> None:
        self._settings = settings
        self._embedding_service = embedding_service
        self._vector_store = vector_store

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        vector = await self._embedding_service.embed_one(question)
        try:
            points = await self._vector_store.search(
                vector,
                limit=self._settings.rag_top_k,
                score_threshold=self._settings.rag_score_threshold,
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
        return chunks
