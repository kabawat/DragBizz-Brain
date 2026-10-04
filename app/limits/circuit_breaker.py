"""Simple circuit breaker for provider / optional RAG dependencies."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import StrEnum

from app.core.exceptions import AppError
from app.observability.events import BREAKER_TRANSITION, emit_event
from app.observability.metrics import MetricsRegistry

logger = logging.getLogger(__name__)


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerRecord:
    failures: int = 0
    opened_at: float = 0.0
    state: BreakerState = BreakerState.CLOSED


class CircuitBreaker:
    """In-process breaker. Redis sharing is not required for correctness
    of a single worker's attempt budget; each worker protects itself."""

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._name = name
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._record = _BreakerRecord()
        self._metrics = metrics

    def allow(self) -> None:
        record = self._record
        now = time.monotonic()
        if record.state == BreakerState.OPEN:
            if now - record.opened_at >= self._cooldown:
                record.state = BreakerState.HALF_OPEN
                if self._metrics is not None:
                    self._metrics.set_breaker_state(BreakerState.HALF_OPEN.value)
            else:
                raise AppError(
                    code="AI_DEPENDENCY_UNAVAILABLE",
                    message=f"{self._name} is temporarily unavailable",
                    status_code=503,
                    retryable=True,
                )

    def record_success(self) -> None:
        self._record = _BreakerRecord()
        if self._metrics is not None:
            self._metrics.set_breaker_state(BreakerState.CLOSED.value)

    def record_failure(self) -> None:
        record = self._record
        record.failures += 1
        if (
            record.state == BreakerState.HALF_OPEN
            or record.failures >= self._threshold
        ):
            record.state = BreakerState.OPEN
            record.opened_at = time.monotonic()
            logger.warning(
                "Circuit breaker open name=%s failures=%s",
                self._name,
                record.failures,
            )
            if self._metrics is not None:
                self._metrics.record_breaker_open(state=BreakerState.OPEN.value)
            emit_event(
                BREAKER_TRANSITION,
                name=self._name,
                state=BreakerState.OPEN.value,
                failures=record.failures,
            )
