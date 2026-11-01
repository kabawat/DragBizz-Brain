import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.observability.context import (
    get_request_id,
    get_session_id,
    get_store_id,
    get_user_id,
)

# Access-log noise: probes and readiness should not dominate INFO output.
_QUIET_ACCESS_PATHS = (
    "/api/v1/health",
    "/api/v1/ready",
    "/health",
    "/ready",
)

# LogRecord builtins + fields we already map explicitly.
_RESERVED_RECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "taskName",
        "request_id",
        "user_id",
        "store_id",
        "session_id",
        "event",
        "metrics",
        "audit",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id

        user_id = getattr(record, "user_id", None) or get_user_id()
        if user_id:
            payload["user_id"] = user_id

        store_id = getattr(record, "store_id", None) or get_store_id()
        if store_id:
            payload["store_id"] = store_id

        session_id = getattr(record, "session_id", None) or get_session_id()
        if session_id:
            payload["session_id"] = session_id

        event = getattr(record, "event", None)
        if event:
            payload["event"] = event

        # Event fields from emit_event(**fields) — failed, tool, error, etc.
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS or key.startswith("_"):
                continue
            if value is None:
                continue
            payload[key] = value

        metrics = getattr(record, "metrics", None)
        if isinstance(metrics, dict):
            payload["metrics"] = metrics

        audit = getattr(record, "audit", None)
        if isinstance(audit, dict):
            payload["audit"] = audit

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class _QuietAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(path in message for path in _QUIET_ACCESS_PATHS)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Outbound HTTP success lines are noise; keep failures/warnings.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    access = logging.getLogger("uvicorn.access")
    access.addFilter(_QuietAccessFilter())
