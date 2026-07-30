"""Redis backends for sessions, idempotency, and confirmations."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.confirmations import RedisConfirmationStore
from app.core.exceptions import AppError
from app.idempotency import RedisIdempotencyStore, build_idempotency_key
from app.schemas.tool import ToolResult
from app.sessions import RedisSessionStore, SessionTurn

STORE_ID = "507f1f77bcf86cd799439011"
SESSION_ID = "sess-redis-1"
USER_ID = "user-1"
INVOICE_ID = "807f1f77bcf86cd799439011"


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

    async def expire(self, key: str, ttl: int) -> None:
        if key in self.kv:
            self.ttls[key] = ttl

    async def delete(self, key: str) -> None:
        self.kv.pop(key, None)
        self.ttls.pop(key, None)


class BrokenRedis:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis down")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise ConnectionError("redis down")

    async def expire(self, key: str, ttl: int) -> None:
        raise ConnectionError("redis down")

    async def delete(self, key: str) -> None:
        raise ConnectionError("redis down")


def test_redis_session_roundtrip_and_ownership() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis, ttl_seconds=60, max_turns=5)

    async def run() -> None:
        await store.append_turn(
            session_id=SESSION_ID,
            user_id=USER_ID,
            store_id=STORE_ID,
            turn=SessionTurn(user_text="hi", assistant_text="hello"),
        )
        history = await store.load_history(
            session_id=SESSION_ID, user_id=USER_ID, store_id=STORE_ID
        )
        assert len(history) == 1
        assert history[0].user_text == "hi"
        assert redis.ttls[f"ai:session:{SESSION_ID}"] == 60

        with pytest.raises(AppError) as exc:
            await store.load_history(
                session_id=SESSION_ID,
                user_id="other",
                store_id=STORE_ID,
            )
        assert exc.value.code == "SESSION_FORBIDDEN"

    asyncio.run(run())


def test_redis_session_fail_open_on_outage() -> None:
    store = RedisSessionStore(BrokenRedis(), ttl_seconds=60)

    async def run() -> None:
        history = await store.load_history(
            session_id=SESSION_ID, user_id=USER_ID, store_id=STORE_ID
        )
        assert history == []
        await store.append_turn(
            session_id=SESSION_ID,
            user_id=USER_ID,
            store_id=STORE_ID,
            turn=SessionTurn(user_text="hi", assistant_text="ok"),
        )

    asyncio.run(run())


def test_redis_idempotency_put_get_and_fail_closed() -> None:
    redis = FakeRedis()
    store = RedisIdempotencyStore(redis, ttl_seconds=120)
    key = build_idempotency_key(
        session_id=SESSION_ID,
        tool_name="create_customer",
        arguments={"storeId": STORE_ID, "name": "A"},
    )
    result = ToolResult(
        tool="create_customer", success=True, data={"id": "c1"}
    )

    async def run() -> None:
        await store.put(key, result)
        cached = await store.get(key)
        assert cached is not None
        assert cached.data == {"id": "c1"}
        assert redis.ttls[key] == 120

        await store.put(
            key, ToolResult(tool="create_customer", success=False, data={})
        )
        assert (await store.get(key)).success is True

        broken = RedisIdempotencyStore(BrokenRedis(), ttl_seconds=120)
        with pytest.raises(AppError) as exc:
            await broken.get(key)
        assert exc.value.code == "AI_STORE_UNAVAILABLE"

    asyncio.run(run())


def test_redis_confirmation_create_consume_and_fail_closed() -> None:
    redis = FakeRedis()
    store = RedisConfirmationStore(redis, ttl_seconds=300)

    async def run() -> None:
        record = await store.create(
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
            type="invoice_release",
            draft_id=INVOICE_ID,
            summary={"total": 10},
            tool_name="release_invoice",
            arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
        )
        got = await store.get(
            record.confirmation_id,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
        )
        assert got.draft_id == INVOICE_ID

        consumed = await store.consume(
            record.confirmation_id,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
            draft_id=INVOICE_ID,
        )
        assert consumed.draft_id == INVOICE_ID

        with pytest.raises(AppError) as exc:
            await store.consume(
                record.confirmation_id,
                user_id=USER_ID,
                store_id=STORE_ID,
                session_id=SESSION_ID,
                draft_id=INVOICE_ID,
            )
        assert exc.value.code == "CONFIRMATION_REQUIRED"

        broken = RedisConfirmationStore(BrokenRedis(), ttl_seconds=300)
        with pytest.raises(AppError) as exc:
            await broken.create(
                user_id=USER_ID,
                store_id=STORE_ID,
                session_id=SESSION_ID,
                type="invoice_release",
                draft_id=INVOICE_ID,
                summary={},
                tool_name="release_invoice",
                arguments={},
            )
        assert exc.value.code == "AI_STORE_UNAVAILABLE"

    asyncio.run(run())


def test_redis_confirmation_expired_by_payload() -> None:
    redis = FakeRedis()
    store = RedisConfirmationStore(redis, ttl_seconds=300)

    async def run() -> None:
        record = await store.create(
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
            type="invoice_release",
            draft_id=INVOICE_ID,
            summary={},
            tool_name="release_invoice",
            arguments={},
        )
        # Force payload expiry while key still present.
        key = f"ai:confirmation:{record.confirmation_id}"
        import json

        payload = json.loads(redis.kv[key])
        payload["expires_at"] = time.time() - 1
        redis.kv[key] = json.dumps(payload)

        with pytest.raises(AppError) as exc:
            await store.get(
                record.confirmation_id,
                user_id=USER_ID,
                store_id=STORE_ID,
                session_id=SESSION_ID,
            )
        assert exc.value.code == "CONFIRMATION_EXPIRED"

    asyncio.run(run())
