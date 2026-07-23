from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings
from app.rag.chunker import DocumentChunk

logger = logging.getLogger(__name__)


class VectorStore:
    """Thin Qdrant wrapper: collection bootstrap + point maintenance.

    Search lands in the RAG retrieval step.
    """

    def __init__(
        self,
        settings: Settings,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            prefer_grpc=False,
            timeout=settings.request_timeout_seconds,
            check_compatibility=False,
        )

    @property
    def collection_name(self) -> str:
        return self._settings.qdrant_collection

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def ping(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:
            logger.debug("Qdrant ping failed", exc_info=True)
            return False

    async def is_ready(self) -> bool:
        return await self.ping()

    async def ensure_collection(self) -> None:
        name = self.collection_name
        exists = await self._collection_exists(name)
        if exists:
            logger.info("Qdrant collection already present: %s", name)
            return

        await self._client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(
                size=self._settings.embedding_dimensions,
                distance=qmodels.Distance.COSINE,
            ),
        )
        logger.info(
            "Created Qdrant collection %s (dims=%s, distance=cosine)",
            name,
            self._settings.embedding_dimensions,
        )

    async def upsert_chunks(
        self, chunks: list[DocumentChunk], vectors: list[list[float]]
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        if not chunks:
            return

        points = [
            qmodels.PointStruct(
                id=chunk.id,
                vector=vector,
                payload={"text": chunk.content, **chunk.metadata},
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self._client.upsert(
            collection_name=self.collection_name, points=points, wait=True
        )

    async def list_point_ids(self) -> set[str]:
        ids: set[str] = set()
        offset = None
        while True:
            records, offset = await self._client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            ids.update(str(record.id) for record in records)
            if offset is None:
                return ids

    async def search(
        self,
        vector: list[float],
        *,
        limit: int,
        score_threshold: float,
    ) -> list[qmodels.ScoredPoint]:
        response = await self._client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return response.points

    async def delete_points(self, ids: list[str]) -> None:
        if not ids:
            return
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.PointIdsList(points=list(ids)),
            wait=True,
        )

    async def _collection_exists(self, name: str) -> bool:
        exists_fn = getattr(self._client, "collection_exists", None)
        if callable(exists_fn):
            result: Any = await exists_fn(name)
            return bool(result)

        collections = await self._client.get_collections()
        return any(c.name == name for c in collections.collections)
