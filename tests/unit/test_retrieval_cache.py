"""FAQ RAG retrieval + docs-block cache."""

from __future__ import annotations

import asyncio

from app.rag.models import RetrievedChunk
from app.rag.retrieval_cache import (
    InMemoryRagCache,
    NoOpRagCache,
    RedisRagCache,
    build_rag_cache,
)

CHUNK = RetrievedChunk(
    id="c1",
    text="POS steps.",
    metadata={"source": "invoice-pos.md"},
    score=0.9,
)


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kv[key] = value
        if ex is not None:
            self.ttls[key] = ex


class BrokenRedis:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis down")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise ConnectionError("redis down")


def test_build_rag_cache_disabled_when_ttl_zero() -> None:
    assert isinstance(build_rag_cache(None, ttl_seconds=0), NoOpRagCache)


def test_inmemory_chunks_and_docs_roundtrip() -> None:
    cache = InMemoryRagCache(ttl_seconds=60)

    async def run() -> None:
        assert (
            await cache.get_chunks(
                "POS kaise?", top_k=5, score_threshold=0.3
            )
            is None
        )
        await cache.set_chunks(
            "POS kaise?",
            top_k=5,
            score_threshold=0.3,
            chunks=[CHUNK],
        )
        hit = await cache.get_chunks(
            "  pos   kaise? ", top_k=5, score_threshold=0.3
        )
        assert hit is not None
        assert hit[0].text == "POS steps."

        await cache.set_documentation_block(
            "POS kaise?", budget=1000, block="[1] steps"
        )
        assert (
            await cache.get_documentation_block("pos kaise?", budget=1000)
            == "[1] steps"
        )

    asyncio.run(run())


def test_redis_chunks_roundtrip_and_fail_open() -> None:
    redis = FakeRedis()
    cache = RedisRagCache(redis, ttl_seconds=120)

    async def run() -> None:
        await cache.set_chunks(
            "q", top_k=5, score_threshold=0.3, chunks=[CHUNK]
        )
        hit = await cache.get_chunks("q", top_k=5, score_threshold=0.3)
        assert hit is not None
        assert hit[0].id == "c1"
        assert any(key.startswith("ai:rag:chunks:") for key in redis.kv)
        assert 120 in redis.ttls.values()

        broken = RedisRagCache(BrokenRedis(), ttl_seconds=60)
        assert (
            await broken.get_chunks("q", top_k=5, score_threshold=0.3) is None
        )
        await broken.set_chunks(
            "q", top_k=5, score_threshold=0.3, chunks=[CHUNK]
        )

    asyncio.run(run())
