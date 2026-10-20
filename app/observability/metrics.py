"""In-process operational counters exposed via GET /api/v1/admin/metrics.

Per-instance by design — this process only, not a cluster aggregate.
Detailed per-request metrics stay in structured logs. Never label with
userId, sessionId, or storeId (high cardinality).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Fixed latency buckets (ms) for in-process percentile estimates.
_LATENCY_BUCKETS_MS = (
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
    30_000.0,
    float("inf"),
)


@dataclass
class _LatencyHistogram:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    buckets: list[int] = field(
        default_factory=lambda: [0] * len(_LATENCY_BUCKETS_MS)
    )

    def record(self, latency_ms: float) -> None:
        self.count += 1
        self.total_ms += latency_ms
        self.max_ms = max(self.max_ms, latency_ms)
        for index, bound in enumerate(_LATENCY_BUCKETS_MS):
            if latency_ms <= bound:
                self.buckets[index] += 1
                return

    def _percentile(self, percentile: float) -> float:
        if self.count == 0:
            return 0.0
        target = max(1, int(round(self.count * percentile / 100.0)))
        cumulative = 0
        for index, bound in enumerate(_LATENCY_BUCKETS_MS):
            cumulative += self.buckets[index]
            if cumulative >= target:
                if bound == float("inf"):
                    return round(self.max_ms, 1)
                return round(bound, 1)
        return round(self.max_ms, 1)

    def snapshot(self) -> dict[str, float]:
        avg = round(self.total_ms / self.count, 1) if self.count else 0.0
        return {
            "avgMs": avg,
            "maxMs": round(self.max_ms, 1),
            "p50Ms": self._percentile(50),
            "p95Ms": self._percentile(95),
            "p99Ms": self._percentile(99),
        }


@dataclass
class _ToolCounter:
    executions: int = 0
    failures: int = 0
    total_ms: float = 0.0

    def record(self, *, success: bool, latency_ms: float | None = None) -> None:
        self.executions += 1
        if not success:
            self.failures += 1
        if latency_ms is not None:
            self.total_ms += latency_ms


@dataclass
class MetricsRegistry:
    """Process-local counters. GET /admin/metrics is this instance only."""

    _chat_requests: int = 0
    _chat_errors: int = 0
    _cap_blocks: int = 0
    _chat_latency: _LatencyHistogram = field(default_factory=_LatencyHistogram)
    _confirm_requests: int = 0
    _confirm_outcomes: dict[str, int] = field(default_factory=dict)
    _provider_calls: int = 0
    _provider_errors: int = 0
    _provider_retries: int = 0
    _provider_fallbacks: int = 0
    _provider_latency: _LatencyHistogram = field(default_factory=_LatencyHistogram)
    _rag_retrieves: int = 0
    _rag_failures: int = 0
    _rag_cache_hits: int = 0
    _rag_latency: _LatencyHistogram = field(default_factory=_LatencyHistogram)
    _tools: dict[str, _ToolCounter] = field(default_factory=dict)
    _rate_limited: int = 0
    _concurrency_limited: int = 0
    _budget_exceeded: int = 0
    _breaker_opens: int = 0
    _breaker_state: str = "closed"
    _failures_by_category: dict[str, int] = field(default_factory=dict)
    _parallel_batches: int = 0
    _parallel_tools: int = 0
    _cancels: int = 0
    _stream_requests: int = 0
    _stream_completed: int = 0
    _stream_aborted: int = 0
    _stream_ttft: _LatencyHistogram = field(default_factory=_LatencyHistogram)
    _token_input: int = 0
    _token_output: int = 0
    _token_total: int = 0
    _token_actual_calls: int = 0
    _token_unavailable_calls: int = 0
    _context_system: int = 0
    _context_history: int = 0
    _context_tool_schemas: int = 0
    _context_tool_results: int = 0
    _context_rag: int = 0
    _compacted_tokens: int = 0
    _removed_schema_tokens: int = 0
    _removed_result_tokens: int = 0

    def record_chat(self, latency_ms: float, *, error: bool = False) -> None:
        self._chat_requests += 1
        if error:
            self._chat_errors += 1
        self._chat_latency.record(latency_ms)

    def record_confirm(self, *, status: str) -> None:
        self._confirm_requests += 1
        self._confirm_outcomes[status] = self._confirm_outcomes.get(status, 0) + 1

    def record_cap_block(self) -> None:
        self._cap_blocks += 1

    def record_provider_call(
        self,
        latency_ms: float,
        *,
        error: bool,
        retry: bool = False,
        fallback: bool = False,
    ) -> None:
        self._provider_calls += 1
        if error:
            self._provider_errors += 1
        if retry:
            self._provider_retries += 1
        if fallback:
            self._provider_fallbacks += 1
        self._provider_latency.record(latency_ms)

    def record_rag(
        self,
        latency_ms: float,
        *,
        failed: bool = False,
        cache_hit: bool = False,
    ) -> None:
        self._rag_retrieves += 1
        if failed:
            self._rag_failures += 1
        if cache_hit:
            self._rag_cache_hits += 1
        self._rag_latency.record(latency_ms)

    def record_tool(
        self, tool: str, *, success: bool, latency_ms: float | None = None
    ) -> None:
        counter = self._tools.setdefault(tool, _ToolCounter())
        counter.record(success=success, latency_ms=latency_ms)

    def record_rate_limited(self) -> None:
        self._rate_limited += 1

    def record_concurrency_limited(self) -> None:
        self._concurrency_limited += 1

    def record_budget_exceeded(self) -> None:
        self._budget_exceeded += 1

    def record_breaker_open(self, *, state: str = "open") -> None:
        self._breaker_opens += 1
        self._breaker_state = state

    def set_breaker_state(self, state: str) -> None:
        self._breaker_state = state

    def record_failure_category(self, category: str) -> None:
        self._failures_by_category[category] = (
            self._failures_by_category.get(category, 0) + 1
        )

    def record_parallel_batch(self, tool_count: int) -> None:
        self._parallel_batches += 1
        self._parallel_tools += max(0, tool_count)

    def record_cancel(self) -> None:
        self._cancels += 1

    def record_stream_request(self) -> None:
        self._stream_requests += 1

    def record_stream_completed(self) -> None:
        self._stream_completed += 1

    def record_stream_aborted(self) -> None:
        self._stream_aborted += 1

    def record_stream_ttft(self, ttft_ms: float) -> None:
        self._stream_ttft.record(ttft_ms)

    def record_token_usage(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        usage_source: str = "unavailable",
    ) -> None:
        if input_tokens:
            self._token_input += input_tokens
        if output_tokens:
            self._token_output += output_tokens
        if input_tokens or output_tokens:
            self._token_total += (input_tokens or 0) + (output_tokens or 0)
        if usage_source == "actual":
            self._token_actual_calls += 1
        elif usage_source == "unavailable":
            self._token_unavailable_calls += 1

    def record_context_estimate(
        self,
        *,
        system: int = 0,
        history: int = 0,
        tool_schemas: int = 0,
        tool_results: int = 0,
        rag: int = 0,
    ) -> None:
        self._context_system += system
        self._context_history += history
        self._context_tool_schemas += tool_schemas
        self._context_tool_results += tool_results
        self._context_rag += rag

    def record_compaction(
        self,
        *,
        compacted: int = 0,
        removed_schemas: int = 0,
        removed_results: int = 0,
    ) -> None:
        self._compacted_tokens += compacted
        self._removed_schema_tokens += removed_schemas
        self._removed_result_tokens += removed_results

    def snapshot(self) -> dict:
        executions = sum(c.executions for c in self._tools.values())
        failures = sum(c.failures for c in self._tools.values())
        success_rate = (
            round((executions - failures) / executions, 4) if executions else None
        )
        confirm_outcomes = {
            status: self._confirm_outcomes.get(status, 0)
            for status in ("SUCCEEDED", "FAILED", "UNKNOWN", "REJECTED")
        }
        for status, count in sorted(self._confirm_outcomes.items()):
            confirm_outcomes.setdefault(status, count)
        return {
            "scope": "instance",
            "chat": {
                "requests": self._chat_requests,
                "errors": self._chat_errors,
                "capBlocked": self._cap_blocks,
                "latency": self._chat_latency.snapshot(),
            },
            "confirm": {
                "requests": self._confirm_requests,
                "outcomes": confirm_outcomes,
            },
            "provider": {
                "calls": self._provider_calls,
                "errors": self._provider_errors,
                "retries": self._provider_retries,
                "fallbacks": self._provider_fallbacks,
                "latency": self._provider_latency.snapshot(),
            },
            "rag": {
                "retrieves": self._rag_retrieves,
                "failures": self._rag_failures,
                "cacheHits": self._rag_cache_hits,
                "latency": self._rag_latency.snapshot(),
            },
            "tools": {
                "executions": executions,
                "failures": failures,
                "successRate": success_rate,
                "byTool": {
                    name: {
                        "executions": counter.executions,
                        "failures": counter.failures,
                        "avgMs": (
                            round(counter.total_ms / counter.executions, 1)
                            if counter.executions and counter.total_ms
                            else 0.0
                        ),
                    }
                    for name, counter in sorted(self._tools.items())
                },
            },
            "limits": {
                "rateLimited": self._rate_limited,
                "concurrencyLimited": self._concurrency_limited,
                "budgetExceeded": self._budget_exceeded,
                "capBlocked": self._cap_blocks,
            },
            "breaker": {
                "opens": self._breaker_opens,
                "state": self._breaker_state,
            },
            "failures": {
                "byCategory": dict(sorted(self._failures_by_category.items())),
            },
            "parallel": {
                "batches": self._parallel_batches,
                "tools": self._parallel_tools,
            },
            "cancel": {"count": self._cancels},
            "stream": {
                "requests": self._stream_requests,
                "completed": self._stream_completed,
                "aborted": self._stream_aborted,
                "ttft": self._stream_ttft.snapshot(),
            },
            "tokens": {
                "input": self._token_input,
                "output": self._token_output,
                "total": self._token_total,
                "actualCalls": self._token_actual_calls,
                "unavailableCalls": self._token_unavailable_calls,
            },
            "context": {
                "system": self._context_system,
                "history": self._context_history,
                "toolSchemas": self._context_tool_schemas,
                "toolResults": self._context_tool_results,
                "rag": self._context_rag,
                "compacted": self._compacted_tokens,
                "removedSchemas": self._removed_schema_tokens,
                "removedResults": self._removed_result_tokens,
            },
        }
