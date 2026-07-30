"""In-process operational counters exposed via GET /api/v1/admin/metrics.

Per-instance by design (like a Prometheus target). Detailed per-request
metrics stay in structured logs; this answers "how is the service doing
right now" without extra infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Latency:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def record(self, latency_ms: float) -> None:
        self.count += 1
        self.total_ms += latency_ms
        self.max_ms = max(self.max_ms, latency_ms)

    def snapshot(self) -> dict[str, float]:
        avg = round(self.total_ms / self.count, 1) if self.count else 0.0
        return {"avgMs": avg, "maxMs": round(self.max_ms, 1)}


@dataclass
class _ToolCounter:
    executions: int = 0
    failures: int = 0


@dataclass
class MetricsRegistry:
    _chat_requests: int = 0
    _cap_blocks: int = 0
    _chat_latency: _Latency = field(default_factory=_Latency)
    _provider_calls: int = 0
    _provider_errors: int = 0
    _provider_latency: _Latency = field(default_factory=_Latency)
    _tools: dict[str, _ToolCounter] = field(default_factory=dict)

    def record_chat(self, latency_ms: float) -> None:
        self._chat_requests += 1
        self._chat_latency.record(latency_ms)

    def record_cap_block(self) -> None:
        self._cap_blocks += 1

    def record_provider_call(self, latency_ms: float, *, error: bool) -> None:
        self._provider_calls += 1
        if error:
            self._provider_errors += 1
        self._provider_latency.record(latency_ms)

    def record_tool(self, tool: str, *, success: bool) -> None:
        counter = self._tools.setdefault(tool, _ToolCounter())
        counter.executions += 1
        if not success:
            counter.failures += 1

    def snapshot(self) -> dict:
        executions = sum(c.executions for c in self._tools.values())
        failures = sum(c.failures for c in self._tools.values())
        success_rate = (
            round((executions - failures) / executions, 4) if executions else None
        )
        return {
            "chat": {
                "requests": self._chat_requests,
                "capBlocked": self._cap_blocks,
                "latency": self._chat_latency.snapshot(),
            },
            "provider": {
                "calls": self._provider_calls,
                "errors": self._provider_errors,
                "latency": self._provider_latency.snapshot(),
            },
            "tools": {
                "executions": executions,
                "failures": failures,
                "successRate": success_rate,
                "byTool": {
                    name: {
                        "executions": counter.executions,
                        "failures": counter.failures,
                    }
                    for name, counter in sorted(self._tools.items())
                },
            },
        }
