"""Short-TTL cache for FAQ RAG chunks and documentation prompt fragments.

Redis when ``AI_REDIS_URL`` is set; otherwise in-process. Fail-open on Redis
errors so chat never depends on the cache. TTL ``0`` disables caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Protocol

from app.rag.models import RetrievedChunk

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
_CHUNKS_PREFIX = "ai:rag:chunks"
_DOCS_PREFIX = "ai:rag:docs"


class RagCache(Protocol):
    async def get_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
    ) -> list[RetrievedChunk] | None: ...

    async def set_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
        chunks: list[RetrievedChunk],
    ) -> None: ...

    async def get_documentation_block(
        self, question: str, *, budget: int
    ) -> str | None: ...

    async def set_documentation_block(
        self, question: str, *, budget: int, block: str
    ) -> None: ...


class NoOpRagCache:
    """Disabled cache (``AI_RAG_CACHE_TTL_SECONDS=0``)."""

    async def get_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
    ) -> list[RetrievedChunk] | None:
        return None

    async def set_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
        chunks: list[RetrievedChunk],
    ) -> None:
        return None

    async def get_documentation_block(
        self, question: str, *, budget: int
    ) -> str | None:
        return None

    async def set_documentation_block(
        self, question: str, *, budget: int, block: str
    ) -> None:
        return None


class InMemoryRagCache:
    def __init__(self, *, ttl_seconds: int, clock: Clock | None = None) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._chunks: dict[str, tuple[float, list[RetrievedChunk]]] = {}
        self._docs: dict[str, tuple[float, str]] = {}

    async def get_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
    ) -> list[RetrievedChunk] | None:
        key = _chunks_key(question, top_k=top_k, score_threshold=score_threshold)
        entry = self._chunks.get(key)
        if entry is None:
            return None
        expires_at, chunks = entry
        if self._clock() >= expires_at:
            self._chunks.pop(key, None)
            return None
        return [chunk.model_copy() for chunk in chunks]

    async def set_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
        chunks: list[RetrievedChunk],
    ) -> None:
        key = _chunks_key(question, top_k=top_k, score_threshold=score_threshold)
        self._chunks[key] = (
            self._clock() + self._ttl_seconds,
            [chunk.model_copy() for chunk in chunks],
        )

    async def get_documentation_block(
        self, question: str, *, budget: int
    ) -> str | None:
        key = _docs_key(question, budget=budget)
        entry = self._docs.get(key)
        if entry is None:
            return None
        expires_at, block = entry
        if self._clock() >= expires_at:
            self._docs.pop(key, None)
            return None
        return block

    async def set_documentation_block(
        self, question: str, *, budget: int, block: str
    ) -> None:
        key = _docs_key(question, budget=budget)
        self._docs[key] = (self._clock() + self._ttl_seconds, block)


class RedisRagCache:
    """Shared FAQ RAG cache. Fail-open on Redis errors."""

    def __init__(self, redis_client, *, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def get_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
    ) -> list[RetrievedChunk] | None:
        key = _chunks_key(question, top_k=top_k, score_threshold=score_threshold)
        try:
            raw = await self._redis.get(key)
        except Exception:
            logger.warning("RAG chunk cache get failed", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return [RetrievedChunk.model_validate(item) for item in payload]
        except Exception:
            logger.warning("RAG chunk cache payload corrupt", exc_info=True)
            return None

    async def set_chunks(
        self,
        question: str,
        *,
        top_k: int,
        score_threshold: float,
        chunks: list[RetrievedChunk],
    ) -> None:
        key = _chunks_key(question, top_k=top_k, score_threshold=score_threshold)
        payload = json.dumps(
            [chunk.model_dump() for chunk in chunks], ensure_ascii=False
        )
        try:
            await self._redis.set(key, payload, ex=self._ttl_seconds)
        except Exception:
            logger.warning("RAG chunk cache set failed", exc_info=True)

    async def get_documentation_block(
        self, question: str, *, budget: int
    ) -> str | None:
        key = _docs_key(question, budget=budget)
        try:
            return await self._redis.get(key)
        except Exception:
            logger.warning("RAG docs cache get failed", exc_info=True)
            return None

    async def set_documentation_block(
        self, question: str, *, budget: int, block: str
    ) -> None:
        key = _docs_key(question, budget=budget)
        try:
            await self._redis.set(key, block, ex=self._ttl_seconds)
        except Exception:
            logger.warning("RAG docs cache set failed", exc_info=True)


def build_rag_cache(
    redis_client,
    *,
    ttl_seconds: int,
) -> RagCache:
    if ttl_seconds <= 0:
        return NoOpRagCache()
    if redis_client is not None:
        return RedisRagCache(redis_client, ttl_seconds=ttl_seconds)
    return InMemoryRagCache(ttl_seconds=ttl_seconds)


def _normalize_question(question: str) -> str:
    return " ".join(question.strip().lower().split())


def _hash(parts: str) -> str:
    return hashlib.sha256(parts.encode()).hexdigest()[:32]


def _chunks_key(question: str, *, top_k: int, score_threshold: float) -> str:
    digest = _hash(f"{_normalize_question(question)}|{top_k}|{score_threshold:.4f}")
    return f"{_CHUNKS_PREFIX}:{digest}"


def _docs_key(question: str, *, budget: int) -> str:
    digest = _hash(f"{_normalize_question(question)}|{budget}")
    return f"{_DOCS_PREFIX}:{digest}"
