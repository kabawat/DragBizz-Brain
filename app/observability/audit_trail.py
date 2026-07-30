"""Immutable append-only audit trail for tool executions.

One JSON line per execution. The service only ever opens the file in
append mode and exposes no read/update/delete path; retention and
shipping are ops concerns (see docs/features/ADMIN_AND_OBSERVABILITY.md).
Events must never contain tool arguments or business payloads (PII).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import IO


class AuditTrail:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file: IO[str] = self._path.open("a", encoding="utf-8")

    def append(self, event: dict) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), **event}
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
