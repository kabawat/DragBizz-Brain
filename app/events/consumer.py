"""Redis Stream consumer for DragBizz Domain Events with at-least-once delivery,
group-based pending reclamation, store isolation, and dead-letter handling.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.events.dead_letter import DeadLetterStore
from app.events.handlers.sales_event import SalesEventHandler
from app.events.handlers.stock_event import StockEventHandler
from app.events.schemas import DomainEventEnvelope
from app.insights.cache import InsightCache

if TYPE_CHECKING:
    from app.proactive.stock_monitor import LowStockMonitor

logger = logging.getLogger(__name__)

DEDUP_KEY_PREFIX = "ai:event:processed:"
ATTEMPT_KEY_PREFIX = "ai:event:attempts:"
DEDUP_TTL_SECONDS = 86400  # 24 hours
CHECKPOINT_TIMESTAMP_KEY = "ai:events:checkpoint:last_occurred_at"
CHECKPOINT_EVENT_KEY = "ai:events:checkpoint:last_event_id"
CHECKPOINT_CONTIGUOUS_SEQ_KEY = "ai:events:checkpoint:last_contiguous_seq"
CHECKPOINT_MAX_SEQ_KEY = "ai:events:checkpoint:max_seq"
CHECKPOINT_GAPS_KEY = "ai:events:checkpoint:unprocessed_gaps"
CHECKPOINT_PENDING_PROCESSED_KEY = "ai:events:checkpoint:pending_processed"
SEQ_PROCESSED_PREFIX = "ai:events:seq_processed:"
REPLAY_REQUEST_KEY = "ai:events:replay_request"


class RedisStreamConsumer:
    """Consumes domain events from a Redis Stream using a consumer group."""

    def __init__(
        self,
        redis_client: Any,
        insight_cache: InsightCache,
        dead_letter_store: DeadLetterStore,
        *,
        stream_name: str = "stream:events:domain",
        group_name: str = "group:brain-ai",
        consumer_name: str | None = None,
        min_idle_ms: int = 30000,
        poll_timeout_ms: int = 2000,
        max_retries: int = 3,
        batch_size: int = 10,
        stock_monitor: LowStockMonitor | None = None,
    ) -> None:
        self._redis = redis_client
        self._cache = insight_cache
        self._dead_letter = dead_letter_store
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name or f"brain-{uuid.uuid4().hex[:8]}"
        self.min_idle_ms = min_idle_ms
        self.poll_timeout_ms = poll_timeout_ms
        self.max_retries = max_retries
        self.batch_size = batch_size
        self._stock_monitor = stock_monitor

        self._sales_handler = SalesEventHandler(insight_cache, stock_monitor)
        self._stock_handler = StockEventHandler(insight_cache, stock_monitor)

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._in_flight = False

        # Metrics counters
        self.processed_count = 0
        self.duplicate_count = 0
        self.error_count = 0
        self.dlq_count = 0

    async def ensure_group(self) -> None:
        """Ensures the stream and consumer group exist."""
        try:
            await self._redis.xgroup_create(
                self.stream_name,
                self.group_name,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Created consumer group %s on stream %s",
                self.group_name,
                self.stream_name,
            )
        except Exception as exc:
            # BUSYGROUP means the consumer group already exists, which is normal
            if "BUSYGROUP" in str(exc):
                pass
            else:
                logger.warning(
                    "Unexpected error ensuring consumer group %s: %s",
                    self.group_name,
                    exc,
                )

    async def start(self) -> None:
        """Starts the background consumption loop."""
        if self._running:
            return
        await self.ensure_group()
        await self._dead_letter.ensure_indexes()
        await self.check_and_request_replay()
        self._running = True
        self._task = asyncio.create_task(
            self._consume_loop(), name="brain_event_consumer"
        )
        logger.info(
            "RedisStreamConsumer started (stream=%s, group=%s, consumer=%s)",
            self.stream_name,
            self.group_name,
            self.consumer_name,
        )

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """Stops consuming, drains in-flight messages gracefully, and cancels task."""
        if not self._running:
            return
        self._running = False
        logger.info("Stopping RedisStreamConsumer gracefully...")

        # Wait for any in-flight message to finish processing
        start_time = asyncio.get_running_loop().time()
        while self._in_flight:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= drain_timeout:
                break
            await asyncio.sleep(0.05)

        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        logger.info("RedisStreamConsumer stopped")

    async def _consume_loop(self) -> None:
        """Main loop: reclaims pending messages then reads new messages."""
        while self._running:
            try:
                # 1. Reclaim pending messages idle longer than min_idle_ms
                await self._reclaim_pending()

                # 2. Read new messages
                response = await self._redis.xreadgroup(
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=self.batch_size,
                    block=self.poll_timeout_ms,
                )

                if response:
                    for _s_name, messages in response:
                        for msg_id, fields in messages:
                            if not self._running:
                                break
                            await self._handle_message_safe(msg_id, fields)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    logger.warning("Error in RedisStreamConsumer loop: %s", exc)
                    await asyncio.sleep(1.0)

    async def _reclaim_pending(self) -> None:
        """Reclaims unacknowledged messages idle longer than min_idle_ms."""
        try:
            claim_res = await self._redis.xautoclaim(
                self.stream_name,
                self.group_name,
                self.consumer_name,
                min_idle_time=self.min_idle_ms,
                start_id="0-0",
                count=self.batch_size,
            )
            # xautoclaim returns (next_start_id, messages, ...)
            if claim_res and len(claim_res) >= 2:
                claimed_messages = claim_res[1]
                for msg_id, fields in claimed_messages:
                    logger.info("Reclaimed idle pending message %s", msg_id)
                    await self._handle_message_safe(msg_id, fields)
        except Exception as exc:
            logger.debug("xautoclaim check: %s", exc)

    async def _record_attempt(self, event_id: str) -> int:
        """Increments and returns attempt count for an event in Redis."""
        key = f"{ATTEMPT_KEY_PREFIX}{event_id}"
        try:
            attempts = await self._redis.incr(key)
            await self._redis.expire(key, DEDUP_TTL_SECONDS)
            return int(attempts)
        except Exception:
            return 1

    async def _handle_message_safe(self, msg_id: str, fields: dict[Any, Any]) -> None:
        """Wraps message processing with in-flight state tracking."""
        self._in_flight = True
        try:
            await self.process_message(msg_id, fields)
        finally:
            self._in_flight = False

    async def process_message(self, msg_id: str, fields: dict[Any, Any]) -> bool:
        """Processes a single event message with deduplication, validation, and DLQ."""
        # Normalize fields from bytes if necessary
        normalized: dict[str, Any] = {}
        for k, v in fields.items():
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            val_str = v.decode() if isinstance(v, bytes) else v
            normalized[key_str] = val_str

        event_id = normalized.get("eventId") or str(msg_id)

        # 1. Deduplication check
        dedup_key = f"{DEDUP_KEY_PREFIX}{event_id}"
        try:
            is_processed = await self._redis.get(dedup_key)
            if is_processed:
                self.duplicate_count += 1
                logger.debug("Duplicate event %s detected; acknowledging", event_id)
                await self._redis.xack(self.stream_name, self.group_name, msg_id)
                return True
        except Exception as exc:
            logger.warning("Redis dedup check error for event %s: %s", event_id, exc)

        # 2. Schema parse and validation
        try:
            envelope = DomainEventEnvelope.model_validate(normalized)
        except ValidationError as val_err:
            self.error_count += 1
            attempts = await self._record_attempt(event_id)
            logger.error("Event validation failed for message %s: %s", msg_id, val_err)
            # Schema failures cannot be recovered by simple retries
            await self._dead_letter.record_failure(
                event_id=event_id,
                event_type=normalized.get("eventType", "unknown"),
                event_version=normalized.get("eventVersion", "unknown"),
                store_id=normalized.get("storeId", "unknown"),
                correlation_id=normalized.get("correlationId"),
                payload=normalized,
                attempts=attempts,
                error=str(val_err),
            )
            self.dlq_count += 1
            # Acknowledge to prevent stream poisoning
            await self._redis.xack(self.stream_name, self.group_name, msg_id)
            return False

        # 3. Dispatch to handler
        try:
            if envelope.event_type == "invoice.released":
                await self._sales_handler.handle(envelope)
            elif envelope.event_type == "stock.intake":
                await self._stock_handler.handle(envelope)
            elif envelope.event_type.startswith("sys."):
                logger.info(
                    "Processed system event %s (%s)",
                    envelope.event_id,
                    envelope.event_type,
                )
            else:
                logger.warning(
                    "No handler registered for event type: %s", envelope.event_type
                )

            # 4. Mark processed in Redis, update checkpoint & acknowledge
            await self._redis.set(dedup_key, "1", ex=DEDUP_TTL_SECONDS)
            if envelope.occurred_at:
                await self._update_checkpoint_monotonically(
                    envelope.occurred_at, envelope.event_id
                )
            if envelope.seq is not None and envelope.seq > 0:
                await self._record_processed_seq(envelope.seq)
            await self._redis.xack(self.stream_name, self.group_name, msg_id)
            self.processed_count += 1
            return True

        except Exception as handler_err:
            self.error_count += 1
            attempts = await self._record_attempt(event_id)
            logger.error(
                "Handler error for event %s (attempt %d/%d): %s",
                event_id,
                attempts,
                self.max_retries,
                handler_err,
                exc_info=True,
            )

            if attempts >= self.max_retries:
                # Retry budget exhausted; persist to Dead Letter Queue
                await self._dead_letter.record_failure(
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                    event_version=envelope.event_version,
                    store_id=envelope.store_id,
                    correlation_id=envelope.correlation_id,
                    payload=envelope.payload,
                    attempts=attempts,
                    error=str(handler_err),
                )
                self.dlq_count += 1
                # Ack after DLQ persistence so stream advances
                await self._redis.xack(self.stream_name, self.group_name, msg_id)
            else:
                # Do NOT ack. Message stays in PEL for retry/reclaim.
                pass
            return False

    async def _record_processed_seq(self, seq: int) -> None:
        """Records processed event sequence, updates contiguous low watermark,
        and tracks gaps so delayed or out-of-order events do not advance
        the replay cursor prematurely.

        Maintains both:
        1. Ephemeral per-event marker (SEQ_PROCESSED_PREFIX) with 7-day TTL.
        2. Durable, non-expiring pending processed set
           (CHECKPOINT_PENDING_PROCESSED_KEY) so gaps unresolved beyond 7 days
           never cause the contiguous watermark to stall or forget previously
           processed events.
        """
        await self._redis.set(f"{SEQ_PROCESSED_PREFIX}{seq}", "1", ex=DEDUP_TTL_SECONDS)

        contig_raw = await self._redis.get(CHECKPOINT_CONTIGUOUS_SEQ_KEY)
        if isinstance(contig_raw, bytes):
            contig_raw = contig_raw.decode()
        contiguous_seq = int(contig_raw) if contig_raw is not None else 0

        max_raw = await self._redis.get(CHECKPOINT_MAX_SEQ_KEY)
        if isinstance(max_raw, bytes):
            max_raw = max_raw.decode()
        max_seq = int(max_raw) if max_raw is not None else 0

        gaps_raw = await self._redis.get(CHECKPOINT_GAPS_KEY)
        if isinstance(gaps_raw, bytes):
            gaps_raw = gaps_raw.decode()
        gaps: set[int] = set(json.loads(gaps_raw)) if gaps_raw else set()

        pending_raw = await self._redis.get(CHECKPOINT_PENDING_PROCESSED_KEY)
        if isinstance(pending_raw, bytes):
            pending_raw = pending_raw.decode()
        pending: set[int] = set(json.loads(pending_raw)) if pending_raw else set()

        gaps.discard(seq)
        if seq > contiguous_seq:
            pending.add(seq)

        if seq > max_seq:
            if seq > contiguous_seq + 1:
                for missing in range(contiguous_seq + 1, seq):
                    if missing not in pending:
                        is_done = await self._redis.get(
                            f"{SEQ_PROCESSED_PREFIX}{missing}"
                        )
                        if not is_done:
                            gaps.add(missing)
            max_seq = seq
            await self._redis.set(CHECKPOINT_MAX_SEQ_KEY, str(max_seq))

        while True:
            candidate = contiguous_seq + 1
            if candidate in pending:
                contiguous_seq = candidate
                pending.discard(candidate)
                gaps.discard(candidate)
            else:
                is_cand_done = await self._redis.get(
                    f"{SEQ_PROCESSED_PREFIX}{candidate}"
                )
                if is_cand_done:
                    contiguous_seq = candidate
                    gaps.discard(candidate)
                else:
                    break

        pending = {p for p in pending if p > contiguous_seq}

        await self._redis.set(CHECKPOINT_CONTIGUOUS_SEQ_KEY, str(contiguous_seq))
        await self._redis.set(
            CHECKPOINT_PENDING_PROCESSED_KEY, json.dumps(sorted(list(pending)))
        )
        await self._redis.set(CHECKPOINT_GAPS_KEY, json.dumps(sorted(list(gaps))))

    async def _update_checkpoint_monotonically(
        self, occurred_at: str, event_id: str
    ) -> None:
        """Updates checkpoint only if event is strictly newer than current.

        Prevents out-of-order events or retries from regressing the replay cursor.
        Tie-breaks equal timestamps with event_id ordering.
        """
        curr_ts = await self._redis.get(CHECKPOINT_TIMESTAMP_KEY)
        if isinstance(curr_ts, bytes):
            curr_ts = curr_ts.decode()
        curr_id = await self._redis.get(CHECKPOINT_EVENT_KEY)
        if isinstance(curr_id, bytes):
            curr_id = curr_id.decode()

        should_advance = (
            (not curr_ts)
            or (occurred_at > curr_ts)
            or (occurred_at == curr_ts and (curr_id is None or event_id > curr_id))
        )

        if should_advance:
            await self._redis.set(CHECKPOINT_TIMESTAMP_KEY, occurred_at)
            await self._redis.set(CHECKPOINT_EVENT_KEY, event_id)

    async def check_and_request_replay(self) -> bool:
        """Detects stream truncation or sequence gaps and posts replay request."""
        try:
            checkpoint = await self.get_checkpoint()
            last_ts = checkpoint.get("last_occurred_at")
            last_id = checkpoint.get("last_event_id")
            contiguous_seq = int(checkpoint.get("last_contiguous_seq", 0))
            max_seq = int(checkpoint.get("max_seq", 0))
            gaps = list(checkpoint.get("gaps", []))

            has_sequence_gap = bool(gaps or (max_seq > contiguous_seq))

            stream_info = await self._redis.xinfo_stream(self.stream_name)
            first_entry = stream_info.get("first-entry")
            is_stream_truncated = False

            if first_entry:
                first_msg_id = (
                    first_entry[0]
                    if isinstance(first_entry, (list, tuple))
                    else str(first_entry)
                )
                if isinstance(first_msg_id, bytes):
                    first_msg_id = first_msg_id.decode()

                groups_info = await self._redis.xinfo_groups(self.stream_name)
                group_info = None
                for g in groups_info:
                    name = g.get("name")
                    if isinstance(name, bytes):
                        name = name.decode()
                    if name == self.group_name:
                        group_info = g
                        break

                if group_info:
                    last_delivered = group_info.get("last-delivered-id", "0-0")
                    if isinstance(last_delivered, bytes):
                        last_delivered = last_delivered.decode()

                    is_stream_truncated = (
                        last_delivered != "0-0" and first_msg_id > last_delivered
                    ) or (last_ts is not None and last_delivered == "0-0")

            if has_sequence_gap or is_stream_truncated:
                existing_req_raw = await self._redis.get(REPLAY_REQUEST_KEY)
                if isinstance(existing_req_raw, bytes):
                    existing_req_raw = existing_req_raw.decode()
                if existing_req_raw:
                    try:
                        existing_req = json.loads(existing_req_raw)
                        existing_seq = existing_req.get("sinceSeq")
                        if (
                            existing_seq is not None
                            and int(existing_seq) < contiguous_seq
                        ):
                            return True
                    except Exception:
                        pass

                req_payload = json.dumps(
                    {
                        "sinceSeq": contiguous_seq,
                        "maxSeq": max_seq,
                        "gaps": gaps,
                        "sinceTimestamp": last_ts,
                        "lastEventId": last_id,
                        "consumer": self.consumer_name,
                    }
                )
                await self._redis.set(REPLAY_REQUEST_KEY, req_payload)
                logger.warning(
                    "Event recovery requested. Posted replay request to %s "
                    "(sinceSeq=%d, maxSeq=%d, gaps=%s, sinceTs=%s, eventId=%s)",
                    REPLAY_REQUEST_KEY,
                    contiguous_seq,
                    max_seq,
                    gaps,
                    last_ts,
                    last_id,
                )
                return True
            return False
        except Exception as exc:
            logger.debug("Automatic replay check skipped: %s", exc)
            return False

    async def get_checkpoint(self) -> dict[str, Any]:
        """Returns the event ID, timestamp, and contiguous sequence checkpoint."""
        last_event_id = await self._redis.get(CHECKPOINT_EVENT_KEY)
        if isinstance(last_event_id, bytes):
            last_event_id = last_event_id.decode()
        last_occurred_at = await self._redis.get(CHECKPOINT_TIMESTAMP_KEY)
        if isinstance(last_occurred_at, bytes):
            last_occurred_at = last_occurred_at.decode()

        contig_raw = await self._redis.get(CHECKPOINT_CONTIGUOUS_SEQ_KEY)
        if isinstance(contig_raw, bytes):
            contig_raw = contig_raw.decode()
        last_contiguous_seq = int(contig_raw) if contig_raw is not None else 0

        max_raw = await self._redis.get(CHECKPOINT_MAX_SEQ_KEY)
        if isinstance(max_raw, bytes):
            max_raw = max_raw.decode()
        max_seq = int(max_raw) if max_raw is not None else 0

        gaps_raw = await self._redis.get(CHECKPOINT_GAPS_KEY)
        if isinstance(gaps_raw, bytes):
            gaps_raw = gaps_raw.decode()
        gaps = json.loads(gaps_raw) if gaps_raw else []

        pending_raw = await self._redis.get(CHECKPOINT_PENDING_PROCESSED_KEY)
        if isinstance(pending_raw, bytes):
            pending_raw = pending_raw.decode()
        pending = json.loads(pending_raw) if pending_raw else []

        return {
            "last_event_id": last_event_id,
            "last_occurred_at": last_occurred_at,
            "last_contiguous_seq": last_contiguous_seq,
            "max_seq": max_seq,
            "gaps": gaps,
            "pending_processed": pending,
        }

    async def get_lag(self) -> dict[str, Any]:
        """Returns stream length, pending entries, and lag visibility."""
        try:
            groups_info = await self._redis.xinfo_groups(self.stream_name)
            group_info = None
            for g in groups_info:
                name = g.get("name")
                if isinstance(name, bytes):
                    name = name.decode()
                if name == self.group_name:
                    group_info = g
                    break
            pending = group_info.get("pending", 0) if group_info else 0
            lag = group_info.get("lag", None) if group_info else None
            stream_info = await self._redis.xinfo_stream(self.stream_name)
            length = stream_info.get("length", 0)
            return {
                "stream": self.stream_name,
                "group": self.group_name,
                "length": length,
                "pending": pending,
                "lag": lag,
            }
        except Exception as exc:
            return {"error": str(exc)}
