"""Dead-letter persistence for unrecoverable or repeatedly failing events."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

DEAD_LETTER_COLLECTION = "ai_event_failures"

SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|token|secret|authorization|api[-_]?key|credit[-_]?card|card[-_]?number)"
)
BEARER_TOKEN_RE = re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+")


def sanitize_payload(obj: Any) -> Any:
    """Recursively redacts sensitive fields like credentials, tokens, or cards."""
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if SENSITIVE_KEY_RE.search(k):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    if isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    return obj


def sanitize_error(error_msg: str) -> str:
    """Redacts bearer tokens and secrets from error strings."""
    if not error_msg:
        return ""
    return BEARER_TOKEN_RE.sub("Bearer [REDACTED]", str(error_msg))


class DeadLetterStore:
    """Durable dead-letter store backed by MongoDB or in-memory fallback."""

    def __init__(self, db: Any | None = None) -> None:
        self._collection = db[DEAD_LETTER_COLLECTION] if db is not None else None
        self._memory_failures: dict[str, dict[str, Any]] = {}

    async def ensure_indexes(self) -> None:
        if self._collection is not None:
            try:
                await self._collection.create_index("eventId", unique=True)
                await self._collection.create_index(
                    [("storeId", 1), ("eventType", 1), ("failedAt", -1)]
                )
            except Exception:
                logger.warning(
                    "Failed to create indexes on %s",
                    DEAD_LETTER_COLLECTION,
                    exc_info=True,
                )

    async def record_failure(
        self,
        *,
        event_id: str,
        event_type: str,
        event_version: str,
        store_id: str,
        correlation_id: str | None,
        payload: dict[str, Any],
        attempts: int,
        error: str,
    ) -> None:
        cleaned_payload = sanitize_payload(payload)
        cleaned_error = sanitize_error(error)
        doc = {
            "eventId": event_id,
            "eventType": event_type,
            "eventVersion": event_version,
            "storeId": store_id,
            "correlationId": correlation_id,
            "payload": cleaned_payload,
            "attempts": attempts,
            "lastError": cleaned_error,
            "failedAt": datetime.now(UTC),
        }

        if self._collection is not None:
            try:
                await self._collection.update_one(
                    {"eventId": event_id},
                    {"$set": doc},
                    upsert=True,
                )
                logger.error(
                    "Recorded dead-letter event %s (type=%s, store=%s, attempts=%d)",
                    event_id,
                    event_type,
                    store_id,
                    attempts,
                )
                return
            except Exception:
                logger.exception(
                    "Failed to persist dead-letter event %s to MongoDB", event_id
                )

        self._memory_failures[event_id] = doc
        logger.error(
            "Recorded in-memory dead-letter event %s (type=%s, attempts=%d)",
            event_id,
            event_type,
            attempts,
        )

    async def get_failure(self, event_id: str) -> dict[str, Any] | None:
        if self._collection is not None:
            try:
                return await self._collection.find_one({"eventId": event_id})
            except Exception:
                pass
        return self._memory_failures.get(event_id)
