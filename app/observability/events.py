"""Stable structured event names for JSON logs (Phase 5).

Events are emitted via the existing JsonFormatter — no new sink.
Never put prompts, tool arguments, or tool result payloads in extras.
"""

from __future__ import annotations

import logging
from typing import Any

from app.observability.context import correlation_fields
from app.observability.redaction import redact_mapping

logger = logging.getLogger("app.observability.events")

CHAT_REQUEST = "chat.request"
CONFIRM_REQUEST = "confirm.request"
MODEL_ATTEMPT = "model.attempt"
TOOL_EXECUTION = "tool.execution"
RAG_RETRIEVE = "rag.retrieve"
CONFIRMATION_LIFECYCLE = "confirmation.lifecycle"
LIMIT_RATE = "limit.rate"
LIMIT_CONCURRENCY = "limit.concurrency"
LIMIT_BUDGET = "limit.budget"
BREAKER_TRANSITION = "breaker.transition"

EVENT_NAMES = frozenset(
    {
        CHAT_REQUEST,
        CONFIRM_REQUEST,
        MODEL_ATTEMPT,
        TOOL_EXECUTION,
        RAG_RETRIEVE,
        CONFIRMATION_LIFECYCLE,
        LIMIT_RATE,
        LIMIT_CONCURRENCY,
        LIMIT_BUDGET,
        BREAKER_TRANSITION,
    }
)


_RESERVED_LOG_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }
)


def emit_event(
    event: str,
    *,
    level: int = logging.INFO,
    metrics: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
    **fields: Any,
) -> None:
    """Emit a named event with correlation + redacted extras."""
    if event not in EVENT_NAMES:
        raise ValueError(f"Unknown observability event: {event}")
    payload = redact_mapping(dict(fields))
    extra: dict[str, Any] = {
        **correlation_fields(),
        "event": event,
    }
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in _RESERVED_LOG_ATTRS:
                extra[f"event_{k}"] = v
            else:
                extra[k] = v
    if metrics is not None:
        extra["metrics"] = redact_mapping(metrics)
    if audit is not None:
        extra["audit"] = redact_mapping(audit)
    logger.log(level, event, extra=extra)

