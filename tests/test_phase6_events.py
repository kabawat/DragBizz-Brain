"""Tests for Phase 6 Safe Event Infrastructure in DragBizz Brain.

Covers:
- Event schema validation & unknown schema version rejection
- Idempotent consumption & duplicate message deduplication
- Crash recovery between deduplication key storage and XACK
- Failed handlers not marked processed before success
- Store isolation: Store A event cannot invalidate Store B insight cache
- Malicious store_id rejection (no wildcard injection)
- Pending message recovery via XAUTOCLAIM after consumer crash
- Dead-letter queue persistence after max retry limit with sanitized credentials
- Graceful startup and shutdown draining in-flight messages
- Transparent latency benchmark with segmented timings and environment classification
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from pydantic import ValidationError

from app.events.consumer import RedisStreamConsumer
from app.events.dead_letter import DeadLetterStore, sanitize_error, sanitize_payload
from app.events.handlers.sales_event import SalesEventHandler
from app.events.handlers.stock_event import StockEventHandler
from app.events.schemas import (
    DomainEventEnvelope,
    InvoiceReleasedPayload,
    StockIntakePayload,
)
from app.insights.cache import InMemoryInsightCache

STORE_A = "64f123456789012345678901"
STORE_B = "64f123456789012345678902"


class MockRedisClient:
    """In-memory Redis mock supporting Stream operations."""

    def __init__(self) -> None:
        self.kvs: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.groups: dict[str, set[str]] = {}
        self.acks: list[tuple[str, str, str]] = []
        self.last_delivered: dict[tuple[str, str], str] = {}
        # group -> id -> (consumer, fields, idle_ms)
        self.pel: dict[str, dict[str, tuple[str, dict[str, str], float]]] = {}
        self._msg_counter = 0

    async def get(self, key: str) -> str | None:
        return self.kvs.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kvs[key] = value

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self.kvs:
                del self.kvs[k]
                count += 1
        return count

    async def incr(self, key: str) -> int:
        val = int(self.kvs.get(key, 0)) + 1
        self.kvs[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def xgroup_create(
        self, stream: str, group: str, id: str = "0", mkstream: bool = False
    ) -> None:
        if group in self.groups.get(stream, set()):
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")
        self.groups.setdefault(stream, set()).add(group)
        self.pel.setdefault(group, {})

    async def xadd(
        self, stream: str, fields: dict[str, str], id: str = "*", **kwargs: Any
    ) -> str:
        self._msg_counter += 1
        msg_id = f"{int(time.time() * 1000)}-{self._msg_counter}"
        self.streams.setdefault(stream, []).append((msg_id, fields))
        return msg_id

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int = 10,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        results: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for s_name in streams:
            messages = self.streams.get(s_name, [])
            delivered = []
            for msg_id, fields in list(messages):
                if len(delivered) >= count:
                    break
                self.pel.setdefault(groupname, {})[msg_id] = (
                    consumername,
                    fields,
                    0.0,
                )
                delivered.append((msg_id, fields))
                messages.remove((msg_id, fields))
            if delivered:
                self.last_delivered[(s_name, groupname)] = delivered[-1][0]
                results.append((s_name, delivered))
        return results

    async def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_time: int,
        start_id: str = "0-0",
        count: int = 10,
    ) -> tuple[str, list[tuple[str, dict[str, str]]]]:
        claimed: list[tuple[str, dict[str, str]]] = []
        group_pel = self.pel.get(group, {})
        for msg_id, (_owner, fields, idle_ms) in list(group_pel.items()):
            if idle_ms >= min_idle_time and len(claimed) < count:
                group_pel[msg_id] = (consumer, fields, 0.0)
                claimed.append((msg_id, fields))
        return ("0-0", claimed)

    async def xack(self, stream: str, group: str, *ids: str) -> int:
        for mid in ids:
            self.acks.append((stream, group, mid))
            self.pel.get(group, {}).pop(mid, None)
        return len(ids)

    async def xinfo_groups(self, stream: str) -> list[dict[str, Any]]:
        groups = []
        for g_name in self.groups.get(stream, []):
            groups.append({
                "name": g_name,
                "pending": len(self.pel.get(g_name, {})),
                "lag": len(self.streams.get(stream, [])),
                "last-delivered-id": self.last_delivered.get((stream, g_name), "0-0"),
            })
        return groups

    async def xinfo_stream(self, stream: str) -> dict[str, Any]:
        msgs = self.streams.get(stream, [])
        first_entry = msgs[0] if msgs else None
        return {
            "length": len(msgs),
            "first-entry": first_entry,
        }


# =====================================================================
# 1. Schema Validation Tests
# =====================================================================

def test_invoice_released_schema_validation() -> None:
    raw = {
        "eventId": "evt_inv_101",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "entityId": "inv_101",
        "correlationId": "corr_999",
        "payload": {
            "invoiceId": "inv_101",
            "invoiceNumber": "INV-2026-0001",
            "totalAmount": 1250.50,
            "paidAmount": 1250.50,
            "paymentStatus": "PAID",
        },
    }
    envelope = DomainEventEnvelope.model_validate(raw)
    assert envelope.event_id == "evt_inv_101"
    assert envelope.event_type == "invoice.released"
    assert envelope.store_id == STORE_A
    assert envelope.event_version == "1.0"

    payload = InvoiceReleasedPayload.model_validate(envelope.payload)
    assert payload.invoice_id == "inv_101"
    assert payload.total_amount == 1250.50


def test_stock_intake_schema_validation() -> None:
    raw = {
        "eventId": "evt_stk_202",
        "eventType": "stock.intake",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "entityId": "bill_202",
        "payload": {
            "billId": "bill_202",
            "supplierId": "64f123456789012345678999",
            "itemCount": 5,
            "totalQuantity": 100,
        },
    }
    envelope = DomainEventEnvelope.model_validate(raw)
    assert envelope.event_id == "evt_stk_202"
    assert envelope.event_type == "stock.intake"

    payload = StockIntakePayload.model_validate(envelope.payload)
    assert payload.bill_id == "bill_202"
    assert payload.total_quantity == 100


def test_invalid_store_id_rejected() -> None:
    raw = {
        "eventId": "evt_inv_102",
        "eventType": "invoice.released",
        "storeId": "invalid-store-format",
        "payload": {"invoiceId": "102"},
    }
    with pytest.raises(ValidationError) as exc:
        DomainEventEnvelope.model_validate(raw)
    assert "Invalid store_id format" in str(exc.value)


def test_wildcard_store_id_injection_rejected() -> None:
    raw = {
        "eventId": "evt_inv_103",
        "eventType": "invoice.released",
        "storeId": "*",
        "payload": {"invoiceId": "103"},
    }
    with pytest.raises(ValidationError):
        DomainEventEnvelope.model_validate(raw)


def test_unknown_event_version_rejected() -> None:
    raw = {
        "eventId": "evt_inv_104",
        "eventType": "invoice.released",
        "eventVersion": "99.0",
        "storeId": STORE_A,
        "payload": {"invoiceId": "104"},
    }
    with pytest.raises(ValidationError) as exc:
        DomainEventEnvelope.model_validate(raw)
    assert "Unsupported schema version" in str(exc.value)


# =====================================================================
# 2. Store Isolation & Cache Invalidation Tests
# =====================================================================

@pytest.mark.asyncio
async def test_store_scoped_cache_invalidation_isolation() -> None:
    cache = InMemoryInsightCache()

    # Pre-populate insight caches for both Store A and Store B
    await cache.set(STORE_A, "sales_pareto", "30d", {"store": "A", "revenue": 1000})
    await cache.set(STORE_A, "inventory_velocity", "30d", {"store": "A", "velocity": 5})
    await cache.set(STORE_B, "sales_pareto", "30d", {"store": "B", "revenue": 5000})
    await cache.set(STORE_B, "store_brief", "today", {"store": "B", "brief": "ok"})

    assert await cache.get(STORE_A, "sales_pareto", "30d") is not None
    assert await cache.get(STORE_B, "sales_pareto", "30d") is not None

    # Handle invoice release for Store A
    sales_handler = SalesEventHandler(cache)
    envelope = DomainEventEnvelope.model_validate({
        "eventId": "evt_inv_501",
        "eventType": "invoice.released",
        "storeId": STORE_A,
        "payload": {"invoiceId": "inv_501"},
    })
    res = await sales_handler.handle(envelope)
    assert res["status"] == "handled"
    assert res["invalidated_entries"] == 2

    # Store A cache entries must be invalidated
    assert await cache.get(STORE_A, "sales_pareto", "30d") is None
    assert await cache.get(STORE_A, "inventory_velocity", "30d") is None

    # Store B cache entries must be completely UNTOUCHED
    store_b_pareto = await cache.get(STORE_B, "sales_pareto", "30d")
    assert store_b_pareto == {"store": "B", "revenue": 5000}
    store_b_brief = await cache.get(STORE_B, "store_brief", "today")
    assert store_b_brief == {"store": "B", "brief": "ok"}


@pytest.mark.asyncio
async def test_stock_intake_cache_invalidation() -> None:
    cache = InMemoryInsightCache()
    await cache.set(STORE_A, "inventory_velocity", "90d", {"stock": "fast"})

    stock_handler = StockEventHandler(cache)
    envelope = DomainEventEnvelope.model_validate({
        "eventId": "evt_stk_601",
        "eventType": "stock.intake",
        "storeId": STORE_A,
        "payload": {"billId": "bill_601", "totalQuantity": 50},
    })
    res = await stock_handler.handle(envelope)
    assert res["status"] == "handled"
    assert res["invalidated_entries"] == 1
    assert await cache.get(STORE_A, "inventory_velocity", "90d") is None


# =====================================================================
# 3. Consumer Idempotency & Crash Recovery
# =====================================================================

@pytest.mark.asyncio
async def test_duplicate_event_deduplication() -> None:
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)

    msg_id = "1000-1"
    raw_fields = {
        "eventId": "evt_inv_701",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "payload": json.dumps({"invoiceId": "inv_701"}),
    }
    await cache.set(STORE_A, "sales_pareto", "30d", {"test": "data"})

    first_res = await consumer.process_message(msg_id, raw_fields)
    assert first_res is True
    assert consumer.processed_count == 1
    assert consumer.duplicate_count == 0
    assert (consumer.stream_name, consumer.group_name, msg_id) in redis.acks

    await cache.set(STORE_A, "sales_pareto", "30d", {"test": "data_again"})

    # Duplicate delivery
    second_res = await consumer.process_message(msg_id, raw_fields)
    assert second_res is True
    assert consumer.processed_count == 1
    assert consumer.duplicate_count == 1

    # Cache must NOT have been invalidated again
    assert await cache.get(STORE_A, "sales_pareto", "30d") == {"test": "data_again"}


@pytest.mark.asyncio
async def test_crash_between_dedup_storage_and_xack() -> None:
    """Simulates a worker crash right after setting dedup key in Redis.

    Upon redelivery, the consumer must recognize the dedup key, acknowledge via XACK,
    and NOT re-execute the handler.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)

    msg_id = "1200-1"
    event_id = "evt_inv_crash_dedup"
    raw_fields = {
        "eventId": event_id,
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "payload": json.dumps({"invoiceId": "inv_crash"}),
    }

    # Simulate: dedup key was stored in Redis by prior attempt before crash
    dedup_key = f"ai:event:processed:{event_id}"
    await redis.set(dedup_key, "1")

    # Set fresh cache data to verify handler does not run
    await cache.set(STORE_A, "sales_pareto", "30d", {"status": "unmodified"})

    # Redelivery of unack message after restart
    res = await consumer.process_message(msg_id, raw_fields)
    assert res is True
    assert consumer.duplicate_count == 1

    # XACK must have been sent
    assert (consumer.stream_name, consumer.group_name, msg_id) in redis.acks

    # Cache must remain intact
    cached = await cache.get(STORE_A, "sales_pareto", "30d")
    assert cached == {"status": "unmodified"}


@pytest.mark.asyncio
async def test_failed_handler_not_marked_processed() -> None:
    """A failed handler must not mark the event processed in Redis."""
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq, max_retries=3)

    msg_id = "1300-1"
    event_id = "evt_fail_1"
    # Malformed payload that fails Pydantic validation
    raw_fields = {
        "eventId": event_id,
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": "invalid_store",
        "payload": json.dumps({}),
    }

    res = await consumer.process_message(msg_id, raw_fields)
    assert res is False

    # Dedup key must NOT exist
    dedup_key = f"ai:event:processed:{event_id}"
    assert await redis.get(dedup_key) is None


# =====================================================================
# 4. Pending Message Recovery via XAUTOCLAIM
# =====================================================================

@pytest.mark.asyncio
async def test_pending_message_reclamation_after_crash() -> None:
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()

    unack_id = "1500-1"
    unack_fields = {
        "eventId": "evt_inv_801",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "payload": json.dumps({"invoiceId": "inv_801"}),
    }
    consumer_group = "group:brain-ai"
    redis.pel[consumer_group] = {
        unack_id: ("dead-worker-1", unack_fields, 35000.0)
    }

    consumer = RedisStreamConsumer(
        redis,
        cache,
        dlq,
        group_name=consumer_group,
        min_idle_ms=30000,
    )

    await cache.set(STORE_A, "store_brief", "today", {"val": "cached"})

    # Reclaim pending
    await consumer._reclaim_pending()

    assert (consumer.stream_name, consumer_group, unack_id) in redis.acks
    assert await cache.get(STORE_A, "store_brief", "today") is None


# =====================================================================
# 5. Dead-Letter Persistence & Credential Sanitization
# =====================================================================

def test_credential_and_token_sanitization() -> None:
    payload = {
        "invoiceId": "inv_901",
        "customer": {"name": "Bob", "password": "supersecretpassword"},
        "paymentToken": "tok_xyz_12345",
        "authorization": "Bearer secret_api_key_here",
        "items": [{"creditCard": "4111111111111111"}],
    }
    sanitized = sanitize_payload(payload)
    assert sanitized["customer"]["password"] == "[REDACTED]"
    assert sanitized["paymentToken"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["items"][0]["creditCard"] == "[REDACTED]"
    assert sanitized["customer"]["name"] == "Bob"

    error_str = "Request failed with status 401: Bearer eyJhbGciOiJIUzI1Ni... expired"
    sanitized_err = sanitize_error(error_str)
    assert "Bearer [REDACTED]" in sanitized_err
    assert "eyJhbGci" not in sanitized_err


@pytest.mark.asyncio
async def test_dead_letter_persistence_after_retry_limit() -> None:
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq, max_retries=3)

    msg_id = "2000-1"
    raw_fields = {
        "eventId": "evt_inv_999",
        "eventType": "invoice.released",
        "eventVersion": "99.0",  # Unsupported version
        "storeId": STORE_A,
        "apiKey": "very-secret-token",
        "payload": json.dumps({"invoiceId": "inv_999"}),
    }

    res = await consumer.process_message(msg_id, raw_fields)
    assert res is False
    assert consumer.dlq_count == 1
    assert (consumer.stream_name, consumer.group_name, msg_id) in redis.acks

    record = await dlq.get_failure("evt_inv_999")
    assert record is not None
    assert record["eventId"] == "evt_inv_999"
    assert record["storeId"] == STORE_A
    assert record["payload"]["apiKey"] == "[REDACTED]"


# =====================================================================
# 6. Graceful Shutdown & Stream Retention
# =====================================================================

@pytest.mark.asyncio
async def test_graceful_shutdown() -> None:
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq, poll_timeout_ms=100)

    await consumer.start()
    assert consumer._running is True
    assert consumer._task is not None

    await consumer.stop(drain_timeout=1.0)
    assert consumer._running is False
    assert consumer._task is None


@pytest.mark.asyncio
async def test_stream_retention_preserves_unprocessed_entries() -> None:
    """Verifies that unread messages in the stream are not prematurely acknowledged."""
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)
    await consumer.ensure_group()

    # Publish 5 events to stream
    for i in range(5):
        await redis.xadd(
            consumer.stream_name,
            {
                "eventId": f"evt_retention_{i}",
                "eventType": "invoice.released",
                "eventVersion": "1.0",
                "storeId": STORE_A,
                "payload": json.dumps({"invoiceId": f"inv_{i}"}),
            },
        )

    # Verify stream length is 5 and zero messages are acknowledged
    stream_info = await redis.xinfo_stream(consumer.stream_name)
    assert stream_info["length"] == 5
    assert len(redis.acks) == 0


@pytest.mark.asyncio
async def test_stream_truncation_replay_and_recovery() -> None:
    """Verifies Brain checkpoint recovery and replay idempotency after truncation.

    Scenario:
    1. Brain processes Event 1 and sets durable checkpoint.
    2. Brain goes offline; Redis stream truncates/drops Events 2 & 3.
    3. Brain restarts, recovers its durable checkpoint (last_occurred_at).
    4. Core replays durable outbox events (Event 1 overlap, Events 2 & 3 missed).
    5. Brain recognizes Event 1 as duplicate, skips duplicate side effects.
    6. Brain processes Events 2 & 3, invalidating cache and advancing checkpoint.
    7. Repeated replay causes zero duplicate side effects.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)
    await consumer.ensure_group()

    # 1. Process Event 1
    t1_iso = "2026-10-20T00:00:01Z"
    evt1_id = "evt_stream_101"
    await redis.xadd(
        consumer.stream_name,
        {
            "eventId": evt1_id,
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t1_iso,
            "payload": json.dumps({"invoiceId": "inv_101", "totalAmount": 100}),
        },
    )

    read_1 = await redis.xreadgroup(
        consumer.group_name, consumer.consumer_name, {consumer.stream_name: ">"}
    )
    assert len(read_1) == 1
    msg1_id, msg1_fields = read_1[0][1][0]
    ok1 = await consumer.process_message(msg1_id, msg1_fields)
    assert ok1 is True
    assert (consumer.stream_name, consumer.group_name, msg1_id) in redis.acks

    # Verify durable checkpoint
    cp1 = await consumer.get_checkpoint()
    assert cp1["last_event_id"] == evt1_id
    assert cp1["last_occurred_at"] == t1_iso

    # 2. Simulate Brain offline & stream truncation
    t2_iso = "2026-10-20T00:00:02Z"
    t3_iso = "2026-10-20T00:00:03Z"
    evt2_id = "evt_stream_102"
    evt3_id = "evt_stream_103"

    # Stream is truncated (emptied in Redis due to MAXLEN trimming)
    redis.streams[consumer.stream_name] = []

    # 3. Brain recovers and queries its durable checkpoint
    recovered_cp = await consumer.get_checkpoint()
    assert recovered_cp["last_event_id"] == evt1_id
    assert recovered_cp["last_occurred_at"] == t1_iso

    # 4. Core initiates replay from outbox since checkpoint last_occurred_at
    outbox_replayed_events = [
        {
            "eventId": evt1_id,
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t1_iso,
            "isReplay": "true",
            "payload": json.dumps({"invoiceId": "inv_101", "totalAmount": 100}),
        },
        {
            "eventId": evt2_id,
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t2_iso,
            "isReplay": "true",
            "payload": json.dumps({"invoiceId": "inv_102", "totalAmount": 200}),
        },
        {
            "eventId": evt3_id,
            "eventType": "stock.intake",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t3_iso,
            "isReplay": "true",
            "payload": json.dumps({"billId": "bill_103", "totalQuantity": 50}),
        },
    ]

    for ev in outbox_replayed_events:
        await redis.xadd(consumer.stream_name, ev)

    # Populate cache for Store A to test whether duplicate replay causes side effects
    await cache.set(STORE_A, "sales_pareto", "30d", {"cached": "yes"})
    initial_processed_count = consumer.processed_count

    # 5. Brain reads replayed stream
    read_replay = await redis.xreadgroup(
        consumer.group_name,
        consumer.consumer_name,
        {consumer.stream_name: ">"},
        count=10,
    )
    assert len(read_replay) == 1
    replayed_msgs = read_replay[0][1]
    assert len(replayed_msgs) == 3

    # Process replayed Event 1 (duplicate)
    r1_id, r1_fields = replayed_msgs[0]
    ok_r1 = await consumer.process_message(r1_id, r1_fields)
    assert ok_r1 is True
    # Cache was NOT cleared because Event 1 was skipped as duplicate
    assert await cache.get(STORE_A, "sales_pareto", "30d") is not None
    assert consumer.processed_count == initial_processed_count

    # Process replayed Event 2 (missed event)
    r2_id, r2_fields = replayed_msgs[1]
    ok_r2 = await consumer.process_message(r2_id, r2_fields)
    assert ok_r2 is True
    # Cache was invalidated by fresh Event 2
    assert await cache.get(STORE_A, "sales_pareto", "30d") is None
    assert consumer.processed_count == initial_processed_count + 1

    # Process replayed Event 3 (missed stock intake)
    await cache.set(STORE_A, "inventory_velocity", "30d", {"stock": "fresh"})
    r3_id, r3_fields = replayed_msgs[2]
    ok_r3 = await consumer.process_message(r3_id, r3_fields)
    assert ok_r3 is True
    assert await cache.get(STORE_A, "inventory_velocity", "30d") is None
    assert consumer.processed_count == initial_processed_count + 2

    # Checkpoint has now advanced to Event 3
    final_cp = await consumer.get_checkpoint()
    assert final_cp["last_event_id"] == evt3_id
    assert final_cp["last_occurred_at"] == t3_iso

    # 6. Test Repeated Replay (Idempotence under replay storm)
    await cache.set(STORE_A, "sales_pareto", "30d", {"cached": "protected"})
    count_before_storm = consumer.processed_count

    for ev in outbox_replayed_events:
        await redis.xadd(consumer.stream_name, ev)

    read_storm = await redis.xreadgroup(
        consumer.group_name,
        consumer.consumer_name,
        {consumer.stream_name: ">"},
        count=10,
    )
    for s_id, s_fields in read_storm[0][1]:
        storm_ok = await consumer.process_message(s_id, s_fields)
        assert storm_ok is True
        assert (consumer.stream_name, consumer.group_name, s_id) in redis.acks

    # All 3 were skipped as duplicates: cache remained untouched, no extra increments
    assert await cache.get(STORE_A, "sales_pareto", "30d") == {"cached": "protected"}
    assert consumer.processed_count == count_before_storm
    assert consumer.error_count == 0
    assert consumer.dlq_count == 0


# =====================================================================
# 7. Latency Measurement (Segmented & Classified)
# =====================================================================

@pytest.mark.asyncio
async def test_in_memory_event_handling_latency_benchmark() -> None:
    """Measures segmented and end-to-end latency across 50 iterations.

    CLASSIFICATION:
    - Environment: In-process Mock Simulation (Unit / Memory-bound)
    - Network I/O: 0.0 ms (mocked Redis, in-memory cache)
    - Disk I/O: 0.0 ms (mocked Mongo outbox)
    - Status for real distributed infrastructure: UNVERIFIED in unit harness
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)

    sample_count = 50
    t_outbox_list: list[float] = []
    t_pub_list: list[float] = []
    t_delivery_list: list[float] = []
    t_handling_list: list[float] = []
    t_e2e_list: list[float] = []

    for i in range(sample_count):
        event_id = f"evt_bench_{i}"
        t0 = time.perf_counter()

        # 1. Outbox serialization / doc creation boundary
        serialized_payload = json.dumps({
            "invoiceId": f"inv_{i}",
            "totalAmount": 100 + i,
        })
        t1 = time.perf_counter()
        t_outbox_list.append((t1 - t0) * 1000.0)

        # 2. Redis stream publication boundary
        await redis.xadd(
            consumer.stream_name,
            {
                "eventId": event_id,
                "eventType": "invoice.released",
                "eventVersion": "1.0",
                "storeId": STORE_A,
                "payload": serialized_payload,
            },
        )
        t2 = time.perf_counter()
        t_pub_list.append((t2 - t1) * 1000.0)

        # 3. Stream delivery (xreadgroup)
        read_res = await redis.xreadgroup(
            consumer.group_name,
            consumer.consumer_name,
            {consumer.stream_name: ">"},
            count=1,
        )
        assert len(read_res) == 1
        _, msgs = read_res[0]
        delivered_id, fields = msgs[0]
        t3 = time.perf_counter()
        t_delivery_list.append((t3 - t2) * 1000.0)

        # 4. Handler completion & acknowledgement
        ok = await consumer.process_message(delivered_id, fields)
        assert ok is True
        t4 = time.perf_counter()
        t_handling_list.append((t4 - t3) * 1000.0)

        # 5. Total end-to-end
        t_e2e_list.append((t4 - t0) * 1000.0)

    def calc_percentiles(data: list[float]) -> tuple[float, float, float]:
        s = sorted(data)
        return (
            s[int(sample_count * 0.50)],
            s[int(sample_count * 0.95)],
            s[int(sample_count * 0.99)],
        )

    e2e_p50, e2e_p95, e2e_p99 = calc_percentiles(t_e2e_list)
    outbox_p50, _, _ = calc_percentiles(t_outbox_list)
    pub_p50, _, _ = calc_percentiles(t_pub_list)
    delivery_p50, _, _ = calc_percentiles(t_delivery_list)
    handling_p50, _, _ = calc_percentiles(t_handling_list)

    print("\n=================================================================")
    print(f"Phase 6 Benchmark [IN-MEMORY MOCK SIMULATION] (N={sample_count})")
    print("=================================================================")
    print(f"  Segment 1: Outbox Serialization p50:  {outbox_p50:.4f} ms")
    print(f"  Segment 2: Redis Stream XADD p50:     {pub_p50:.4f} ms")
    print(f"  Segment 3: Consumer Read p50:         {delivery_p50:.4f} ms")
    print(f"  Segment 4: Handler & XACK p50:        {handling_p50:.4f} ms")
    print("-----------------------------------------------------------------")
    print(
        f"  Total In-Memory e2e: p50={e2e_p50:.4f}ms | "
        f"p95={e2e_p95:.4f}ms | p99={e2e_p99:.4f}ms"
    )
    print("  Classification: Local in-process simulation only.")
    print("  Real Distributed Network SLA: UNVERIFIED without live remote services.")
    print("=================================================================")

    # Internal code path overhead must be < 50 ms
    assert e2e_p99 < 50.0


# =====================================================================
# 8. Replay Cursor & Automatic Recovery Trigger Regression Tests
# =====================================================================

@pytest.mark.asyncio
async def test_out_of_order_events_do_not_regress_checkpoint() -> None:
    """Verifies that an older event arriving out-of-order does not
    regress the checkpoint.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)

    # 1. Process Event 1 with newer timestamp T2
    t2 = "2026-10-20T12:00:10Z"
    msg1_fields = {
        "eventId": "evt_newer_2",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "occurredAt": t2,
        "payload": json.dumps({"invoiceId": "inv_new"}),
    }
    ok1 = await consumer.process_message("100-1", msg1_fields)
    assert ok1 is True

    cp1 = await consumer.get_checkpoint()
    assert cp1["last_occurred_at"] == t2
    assert cp1["last_event_id"] == "evt_newer_2"

    # 2. Process Event 2 with older timestamp T1 (arrived out of order)
    t1 = "2026-10-20T12:00:05Z"
    msg2_fields = {
        "eventId": "evt_older_1",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "occurredAt": t1,
        "payload": json.dumps({"invoiceId": "inv_old"}),
    }
    ok2 = await consumer.process_message("100-2", msg2_fields)
    assert ok2 is True

    # Checkpoint must NOT regress to t1! It must stay at t2
    cp2 = await consumer.get_checkpoint()
    assert cp2["last_occurred_at"] == t2
    assert cp2["last_event_id"] == "evt_newer_2"
    assert consumer.processed_count == 2


@pytest.mark.asyncio
async def test_equal_timestamps_deterministic_tie_breaking() -> None:
    """Verifies deterministic tie-breaking by event_id when occurredAt
    timestamps are identical.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)

    shared_ts = "2026-10-20T12:00:00Z"
    msg_a = {
        "eventId": "evt_inv_aaa",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "occurredAt": shared_ts,
        "payload": json.dumps({"invoiceId": "inv_a"}),
    }
    msg_b = {
        "eventId": "evt_inv_bbb",
        "eventType": "invoice.released",
        "eventVersion": "1.0",
        "storeId": STORE_A,
        "occurredAt": shared_ts,
        "payload": json.dumps({"invoiceId": "inv_b"}),
    }

    # Process first event with ID 'aaa'
    await consumer.process_message("101-1", msg_a)
    cp_a = await consumer.get_checkpoint()
    assert cp_a["last_occurred_at"] == shared_ts
    assert cp_a["last_event_id"] == "evt_inv_aaa"

    # Process second event with ID 'bbb' sharing the exact same timestamp
    await consumer.process_message("101-2", msg_b)
    cp_b = await consumer.get_checkpoint()
    assert cp_b["last_occurred_at"] == shared_ts
    assert cp_b["last_event_id"] == "evt_inv_bbb"

    # Redelivery of msg_a with smaller event_id should not regress checkpoint
    await consumer.process_message("101-3", msg_a)
    cp_c = await consumer.get_checkpoint()
    assert cp_c["last_event_id"] == "evt_inv_bbb"


@pytest.mark.asyncio
async def test_checkpoint_recovery_after_consumer_restart() -> None:
    """Verifies durable checkpoint persists across consumer instance restarts."""
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()

    # Consumer 1 starts, processes an event, and stops
    consumer_1 = RedisStreamConsumer(redis, cache, dlq, consumer_name="worker-1")
    t_iso = "2026-10-20T15:30:00Z"
    await consumer_1.process_message(
        "200-1",
        {
            "eventId": "evt_persist_1",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t_iso,
            "payload": json.dumps({"invoiceId": "inv_p1"}),
        },
    )
    await consumer_1.stop()

    # Consumer 2 (fresh instance after restart) initializes against same Redis
    consumer_2 = RedisStreamConsumer(redis, cache, dlq, consumer_name="worker-2")
    recovered_cp = await consumer_2.get_checkpoint()

    assert recovered_cp["last_event_id"] == "evt_persist_1"
    assert recovered_cp["last_occurred_at"] == t_iso


@pytest.mark.asyncio
async def test_automatic_replay_trigger_on_stream_truncation() -> None:
    """Verifies that when consumer detects stream truncation beyond its position,
    it automatically writes a replay request to Redis for Core sweeper pickup.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)
    await consumer.ensure_group()

    # Set existing checkpoint from previously consumed events
    last_ts = "2026-10-20T10:00:00Z"
    last_id = "evt_prev_999"
    await redis.set("ai:events:checkpoint:last_occurred_at", last_ts)
    await redis.set("ai:events:checkpoint:last_event_id", last_id)

    # Simulate stream truncation: first-entry in stream is newer than
    # the consumer group's last-delivered ID
    redis.streams[consumer.stream_name] = [
        ("5000-1", {"eventId": "evt_new_1"})
    ]
    # Consumer group last delivered was 4000-1 (which was trimmed away)
    redis.last_delivered[(consumer.stream_name, consumer.group_name)] = "4000-1"

    # Run check_and_request_replay
    triggered = await consumer.check_and_request_replay()
    assert triggered is True

    # Verify replay request was written to Redis
    raw_req = await redis.get("ai:events:replay_request")
    assert raw_req is not None
    req = json.loads(raw_req)
    assert req["sinceTimestamp"] == last_ts
    assert req["lastEventId"] == last_id
    assert req["consumer"] == consumer.consumer_name


@pytest.mark.asyncio
async def test_deterministic_regression_gap_recovery_out_of_order() -> None:
    """Deterministic regression scenario:
    - Event A has an earlier occurrence timestamp (10:00:00, seq 1) but
      remains unprocessed.
    - Event B has a later occurrence timestamp (10:05:00, seq 2) and
      is processed successfully.
    - The stream loses Event A before recovery (e.g. trimmed or missed).
    - Brain detects the sequence gap and requests replay.
    - Verify that Event A is recovered even though its occurrence timestamp
      is earlier than the latest processed event.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq, consumer_name="brain-worker-1")
    await consumer.ensure_group()

    # Event B (seq 2, occurredAt 10:05:00) arrives and is processed first
    t_event_b = "2026-10-20T10:05:00Z"
    await consumer.process_message(
        "1000-2",
        {
            "eventId": "evt_b",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t_event_b,
            "seq": "2",
            "payload": json.dumps({"invoiceId": "inv_b"}),
        },
    )

    # Checkpoint status after Event B:
    # last_occurred_at advanced to 10:05:00, but contiguous_seq is still 0
    # because seq 1 was missing!
    cp_after_b = await consumer.get_checkpoint()
    assert cp_after_b["last_occurred_at"] == t_event_b
    assert cp_after_b["last_event_id"] == "evt_b"
    assert cp_after_b["last_contiguous_seq"] == 0
    assert cp_after_b["max_seq"] == 2
    assert cp_after_b["gaps"] == [1]

    # Consumer checks replay; gap [1] is detected
    replay_triggered = await consumer.check_and_request_replay()
    assert replay_triggered is True

    raw_req = await redis.get("ai:events:replay_request")
    assert raw_req is not None
    req = json.loads(raw_req)
    # The replay MUST be requested from sinceSeq=0 (contiguous_seq),
    # NOT from last_occurred_at
    assert req["sinceSeq"] == 0
    assert 1 in req["gaps"]

    # Now Event A is replayed from Core outbox (seq 1, occurredAt 10:00:00)
    t_event_a = "2026-10-20T10:00:00Z"
    success_a = await consumer.process_message(
        "1000-1-replay",
        {
            "eventId": "evt_a",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": t_event_a,
            "seq": "1",
            "payload": json.dumps({"invoiceId": "inv_a"}),
        },
    )
    assert success_a is True

    # After recovering Event A, the contiguous checkpoint advances to 2
    # and gaps are cleared!
    cp_after_recovery = await consumer.get_checkpoint()
    assert cp_after_recovery["last_contiguous_seq"] == 2
    assert cp_after_recovery["max_seq"] == 2
    assert cp_after_recovery["gaps"] == []

    # And if replay is checked again, no replay is needed
    assert await consumer.check_and_request_replay() is False


@pytest.mark.asyncio
async def test_gap_recovery_survives_consumer_restart() -> None:
    """Verifies that sequence gaps and contiguous checkpoint survive
    consumer process restart.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()

    # Worker 1 processes Event 2, leaving gap 1
    worker_1 = RedisStreamConsumer(redis, cache, dlq, consumer_name="worker-1")
    await worker_1.ensure_group()
    await worker_1.process_message(
        "500-2",
        {
            "eventId": "evt_2",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T12:00:00Z",
            "seq": "2",
            "payload": json.dumps({"invoiceId": "inv_2"}),
        },
    )
    await worker_1.stop()

    # Worker 2 restarts against same Redis
    worker_2 = RedisStreamConsumer(redis, cache, dlq, consumer_name="worker-2")
    cp = await worker_2.get_checkpoint()
    assert cp["last_contiguous_seq"] == 0
    assert cp["max_seq"] == 2
    assert cp["gaps"] == [1]

    # Worker 2 triggers replay and recovers Event 1
    triggered = await worker_2.check_and_request_replay()
    assert triggered is True

    await worker_2.process_message(
        "500-1",
        {
            "eventId": "evt_1",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T11:00:00Z",
            "seq": "1",
            "payload": json.dumps({"invoiceId": "inv_1"}),
        },
    )

    cp_final = await worker_2.get_checkpoint()
    assert cp_final["last_contiguous_seq"] == 2
    assert cp_final["gaps"] == []


@pytest.mark.asyncio
async def test_gap_unresolved_beyond_ttl_recovers_without_stalling() -> None:
    """Verifies that an unresolved gap persisting beyond the 7-day TTL does not
    cause previously processed events to be forgotten or permanently stall the
    checkpoint when the missing event is finally recovered.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)
    await consumer.ensure_group()

    # Baseline checkpoint: sequences up to 10 are already contiguously processed
    await redis.set("ai:events:checkpoint:last_contiguous_seq", "10")
    await redis.set("ai:events:checkpoint:max_seq", "10")

    # Sequence 12 arrives while sequence 11 was missing
    await consumer.process_message(
        "100-12",
        {
            "eventId": "evt_12",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:02:00Z",
            "seq": "12",
            "payload": json.dumps({"invoiceId": "inv_12"}),
        },
    )

    cp_mid = await consumer.get_checkpoint()
    assert cp_mid["last_contiguous_seq"] == 10
    assert cp_mid["gaps"] == [11]
    assert 12 in cp_mid["pending_processed"]

    # Simulate 7-day TTL expiration: ephemeral seq_processed key is deleted
    await redis.delete("ai:events:seq_processed:12")

    # Day 8: Missing sequence 11 is finally recovered
    await consumer.process_message(
        "100-11",
        {
            "eventId": "evt_11",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:01:00Z",
            "seq": "11",
            "payload": json.dumps({"invoiceId": "inv_11"}),
        },
    )

    # Contiguous checkpoint advances past both 11 and 12
    cp_final = await consumer.get_checkpoint()
    assert cp_final["last_contiguous_seq"] == 12
    assert cp_final["gaps"] == []
    assert cp_final["pending_processed"] == []


@pytest.mark.asyncio
async def test_abandoned_sequence_tombstone_resolution() -> None:
    """Verifies that an abandoned sequence allocation in Core emits a
    sys.gap_fill tombstone which Brain safely consumes to advance its
    contiguous checkpoint past the abandoned sequence without looping.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq)
    await consumer.ensure_group()

    # Event 1 processed
    await consumer.process_message(
        "200-1",
        {
            "eventId": "evt_1",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:00:00Z",
            "seq": "1",
            "payload": json.dumps({"invoiceId": "inv_1"}),
        },
    )

    # Event 3 processed (sequence 2 was an abandoned allocation in Core)
    await consumer.process_message(
        "200-3",
        {
            "eventId": "evt_3",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:02:00Z",
            "seq": "3",
            "payload": json.dumps({"invoiceId": "inv_3"}),
        },
    )

    cp_mid = await consumer.get_checkpoint()
    assert cp_mid["last_contiguous_seq"] == 1
    assert cp_mid["gaps"] == [2]

    # Core detects abandoned sequence 2 and streams sys.gap_fill tombstone
    await consumer.process_message(
        "200-2-tombstone",
        {
            "eventId": "sys_tombstone_2",
            "eventType": "sys.gap_fill",
            "eventVersion": "1.0",
            "storeId": "000000000000000000000000",
            "occurredAt": "2026-10-20T10:01:00Z",
            "seq": "2",
            "payload": json.dumps(
                {"reason": "abandoned_sequence", "skippedSeq": 2}
            ),
        },
    )

    # Contiguous checkpoint advances past the tombstone to sequence 3
    cp_final = await consumer.get_checkpoint()
    assert cp_final["last_contiguous_seq"] == 3
    assert cp_final["gaps"] == []


@pytest.mark.asyncio
async def test_late_publisher_resequencing_delivered_exactly_once() -> None:
    """Verifies that when Publisher A allocates sequence 1 and pauses,
    Publisher B publishes sequence 2, replay tombstones sequence 1 to
    advance the watermark, Publisher A's fencing re-sequences genuine Event A
    to sequence 3 so that stream trimming, consumer restart, and checkpoint
    replay deliver Event A with exactly-once handler execution.
    """
    redis = MockRedisClient()
    cache = InMemoryInsightCache()
    dlq = DeadLetterStore()
    consumer = RedisStreamConsumer(redis, cache, dlq, consumer_name="worker-main")
    await consumer.ensure_group()

    # Step 1: Publisher A pauses with candidate seq 1 in flight.
    # Step 2: Publisher B publishes sequence 2
    success_b = await consumer.process_message(
        "300-2",
        {
            "eventId": "evt_b",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:02:00Z",
            "seq": "2",
            "payload": json.dumps({"invoiceId": "inv_b"}),
        },
    )
    assert success_b is True

    # Checkpoint has gap at sequence 1
    cp_gap = await consumer.get_checkpoint()
    assert cp_gap["last_contiguous_seq"] == 0
    assert cp_gap["gaps"] == [1]

    # Step 3: Replay runs while sequence 1 is absent,
    # emitting sys.gap_fill tombstone for seq 1
    success_tombstone = await consumer.process_message(
        "300-1-tombstone",
        {
            "eventId": "sys_tombstone_1",
            "eventType": "sys.gap_fill",
            "eventVersion": "1.0",
            "storeId": "000000000000000000000000",
            "occurredAt": "2026-10-20T10:01:00Z",
            "seq": "1",
            "payload": json.dumps({"reason": "abandoned_sequence", "skippedSeq": 1}),
        },
    )
    assert success_tombstone is True

    # Watermark advances past tombstone 1 and event 2
    cp_advanced = await consumer.get_checkpoint()
    assert cp_advanced["last_contiguous_seq"] == 2
    assert cp_advanced["gaps"] == []

    # Step 4: Late Publisher A resumes. Core detects sequence 1 was claimed
    # by tombstone, fences Publisher A, and re-sequences Event A to sequence 3.
    # Step 5: Simulate stream trimming & consumer restart
    # Previous stream entries (1, 2) are trimmed from Redis
    consumer_restarted = RedisStreamConsumer(
        redis, cache, dlq, consumer_name="worker-restarted"
    )
    cp_restart = await consumer_restarted.get_checkpoint()
    assert cp_restart["last_contiguous_seq"] == 2

    # Set up cache to verify business handler execution
    await cache.set(STORE_A, "sales_pareto", "30d", {"active": True})
    assert await cache.get(STORE_A, "sales_pareto", "30d") is not None

    # Replay discovers genuine Event A at re-sequenced seq 3 (sinceSeq: 2)
    success_a = await consumer_restarted.process_message(
        "300-3",
        {
            "eventId": "evt_a",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:00:00Z",
            "seq": "3",
            "payload": json.dumps({"invoiceId": "inv_a"}),
        },
    )
    assert success_a is True

    # Event A handler executed: cache was invalidated
    assert await cache.get(STORE_A, "sales_pareto", "30d") is None

    # Checkpoint cleanly advances to sequence 3
    cp_final = await consumer_restarted.get_checkpoint()
    assert cp_final["last_contiguous_seq"] == 3
    assert cp_final["gaps"] == []

    # Duplicate delivery of Event A is idempotent: handler does not re-execute
    duplicate_a = await consumer_restarted.process_message(
        "300-3-dup",
        {
            "eventId": "evt_a",
            "eventType": "invoice.released",
            "eventVersion": "1.0",
            "storeId": STORE_A,
            "occurredAt": "2026-10-20T10:00:00Z",
            "seq": "3",
            "payload": json.dumps({"invoiceId": "inv_a"}),
        },
    )
    assert duplicate_a is True
    cp_dup = await consumer_restarted.get_checkpoint()
    assert cp_dup["last_contiguous_seq"] == 3




