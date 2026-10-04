"""Immutable append-only audit trail for tool + confirmation events.

One JSON line per event. Append-only; no read/update/delete API.
Retention and shipping are ops concerns.

Non-allowlisted keys are rejected (raise) — never silently dropped,
and the rejected payload is never logged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

# Shared allowlist for tool execution + confirmation lifecycle audits.
AUDIT_ALLOWLIST = frozenset(
    {
        "event",
        "sessionId",
        "userId",
        "storeId",
        "tool",
        "success",
        "errorCode",
        "idempotencyKeyPrefix",
        "cacheHit",
        "confirmationId",
        "type",
        "status",
        "previousStatus",
        "requestId",
    }
)


class AuditTrailError(ValueError):
    """Raised when an audit event contains non-allowlisted keys."""


class AuditTrail:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file: IO[str] = self._path.open("a", encoding="utf-8")

    def append(self, event: dict) -> None:
        unknown = set(event) - AUDIT_ALLOWLIST
        if unknown:
            # Do not include the rejected payload values in the error.
            raise AuditTrailError(
                "Audit event contains non-allowlisted keys: "
                + ", ".join(sorted(unknown))
            )
        record = {"ts": datetime.now(UTC).isoformat(), **event}
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
