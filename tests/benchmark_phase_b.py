"""Repeatable Phase B Benchmark: Sequential vs Parallel Execution and Compaction.

Measures:
1. Two independent read calls (Sequential vs Parallel).
2. Three independent read calls (Sequential vs Parallel).
3. Number of tool calls and rounds.
4. Failure and timeout isolation behavior.
5. Payload sizes (bytes & estimated tokens) before and after compaction.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock

from app.executors.tool_executor import ToolExecutor
from app.orchestrator.context_optimize import compact_result_for_model
from app.rag.chunker import estimate_tokens
from app.schemas.tool import ToolCall, ToolDefinition, ToolResult, ToolRisk
from app.tools.context import ToolContext
from app.tools.registry import ToolRegistry

STORE_ID = "6ad49964d5cb7a1b29d4bb7b"


def _create_mock_registry(delay: float = 0.05) -> ToolRegistry:
    reg = ToolRegistry()

    async def make_handler(name: str):
        async def handler(
            args: dict[str, Any], ctx: ToolContext
        ) -> ToolResult:
            await asyncio.sleep(delay)
            return ToolResult(
                tool=name, success=True, data={"name": name, "items": [1, 2, 3]}
            )

        return handler

    for tool_name in ("tool_a", "tool_b", "tool_c"):
        defn = ToolDefinition(
            name=tool_name,
            description=f"Mock read {tool_name}",
            risk=ToolRisk.READ,
            allows_parallel=True,
            parameters={"type": "object", "properties": {}},
        )
        # Register in async runner
        loop = asyncio.get_event_loop()
        h = loop.run_until_complete(make_handler(tool_name))
        reg.register(defn, h)

    return reg


async def run_benchmark() -> dict[str, Any]:
    delay = 0.05  # 50ms per tool
    reg = ToolRegistry()

    async def mock_handler(name: str):
        async def handler(
            args: dict[str, Any], ctx: ToolContext
        ) -> ToolResult:
            await asyncio.sleep(delay)
            return ToolResult(
                tool=name, success=True, data={"name": name, "items": [1, 2, 3]}
            )

        return handler

    for tool_name in ("tool_a", "tool_b", "tool_c"):
        defn = ToolDefinition(
            name=tool_name,
            description=f"Mock read {tool_name}",
            risk=ToolRisk.READ,
            allows_parallel=True,
            parameters={"type": "object", "properties": {}},
        )
        reg.register(defn, await mock_handler(tool_name))

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())

    # --- 1. Two Read Calls ---
    calls_2 = [
        ToolCall(id="c1", name="tool_a", arguments={"storeId": STORE_ID}),
        ToolCall(id="c2", name="tool_b", arguments={"storeId": STORE_ID}),
    ]

    t0 = time.perf_counter()
    _ = await executor.execute_reads(
        calls_2,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"tool_a", "tool_b"}),
        parallel=False,
    )
    seq_time_2 = time.perf_counter() - t0

    t0 = time.perf_counter()
    res_par_2 = await executor.execute_reads(
        calls_2,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"tool_a", "tool_b"}),
        parallel=True,
    )
    par_time_2 = time.perf_counter() - t0

    # --- 2. Three Read Calls ---
    calls_3 = [
        ToolCall(id="c1", name="tool_a", arguments={"storeId": STORE_ID}),
        ToolCall(id="c2", name="tool_b", arguments={"storeId": STORE_ID}),
        ToolCall(id="c3", name="tool_c", arguments={"storeId": STORE_ID}),
    ]

    t0 = time.perf_counter()
    _ = await executor.execute_reads(
        calls_3,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"tool_a", "tool_b", "tool_c"}),
        parallel=False,
    )
    seq_time_3 = time.perf_counter() - t0

    t0 = time.perf_counter()
    res_par_3 = await executor.execute_reads(
        calls_3,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"tool_a", "tool_b", "tool_c"}),
        parallel=True,
    )
    par_time_3 = time.perf_counter() - t0

    # --- 3. Timeout and Error Isolation ---
    reg_err = ToolRegistry()

    async def timeout_handler(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        await asyncio.sleep(0.2)
        return ToolResult(tool="timeout_tool", success=True, data={})

    async def instant_handler(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(
            tool="instant_tool", success=True, data={"status": "ok"}
        )

    reg_err.register(
        ToolDefinition(
            name="timeout_tool",
            description="Simulates timeout",
            risk=ToolRisk.READ,
            parameters={},
        ),
        timeout_handler,
    )
    reg_err.register(
        ToolDefinition(
            name="instant_tool",
            description="Instant response",
            risk=ToolRisk.READ,
            parameters={},
        ),
        instant_handler,
    )

    executor_err = ToolExecutor(registry=reg_err, retailer=AsyncMock())
    err_calls = [
        ToolCall(
            id="c_err1", name="timeout_tool", arguments={"storeId": STORE_ID}
        ),
        ToolCall(
            id="c_err2", name="instant_tool", arguments={"storeId": STORE_ID}
        ),
    ]
    err_results = await executor_err.execute_reads(
        err_calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"timeout_tool", "instant_tool"}),
        parallel=True,
        tool_timeout_seconds=0.03,
    )

    # --- 4. Payload Compaction Measurements ---
    sample_supplier_raw = {
        "found": True,
        "count": 25,
        "suppliers": [
            {
                "supplierId": f"sup_{i:03d}",
                "name": f"Supplier Partner {i} Pvt Ltd",
                "phone": f"9876543{i:03d}",
                "email": f"partner{i}@example.com",
                "address": f"Plot {i}, Industrial Estate, Phase {i%3 + 1}",
                "gstNumber": f"27AABCU9603R1Z{i%9}",
                "active": True,
                "creditDays": 30,
            }
            for i in range(25)
        ],
    }
    raw_res = ToolResult(
        tool="search_supplier", success=True, data=sample_supplier_raw
    )
    compacted_res = compact_result_for_model(raw_res)

    raw_json = json.dumps(raw_res.data, ensure_ascii=False)
    compacted_json = json.dumps(compacted_res.data, ensure_ascii=False)

    raw_bytes = len(raw_json.encode("utf-8"))
    compacted_bytes = len(compacted_json.encode("utf-8"))
    raw_tokens = estimate_tokens(raw_json)
    compacted_tokens = estimate_tokens(compacted_json)

    return {
        "simulated_tool_delay_ms": delay * 1000,
        "two_calls": {
            "num_calls": len(calls_2),
            "sequential_elapsed_ms": round(seq_time_2 * 1000, 2),
            "parallel_elapsed_ms": round(par_time_2 * 1000, 2),
            "speedup": round(seq_time_2 / max(par_time_2, 0.0001), 2),
            "all_success": all(r.success for r in res_par_2),
        },
        "three_calls": {
            "num_calls": len(calls_3),
            "sequential_elapsed_ms": round(seq_time_3 * 1000, 2),
            "parallel_elapsed_ms": round(par_time_3 * 1000, 2),
            "speedup": round(seq_time_3 / max(par_time_3, 0.0001), 2),
            "all_success": all(r.success for r in res_par_3),
        },
        "error_isolation": {
            "timeout_tool_code": err_results[0].data.get("code"),
            "instant_tool_success": err_results[1].success,
        },
        "compaction": {
            "tool": "search_supplier (25 records)",
            "raw_bytes": raw_bytes,
            "compacted_bytes": compacted_bytes,
            "bytes_reduction_pct": round(
                (1 - compacted_bytes / raw_bytes) * 100, 1
            ),
            "raw_tokens": raw_tokens,
            "compacted_tokens": compacted_tokens,
            "tokens_reduction_pct": round(
                (1 - compacted_tokens / raw_tokens) * 100, 1
            ),
        },
    }


def test_phase_b_benchmark() -> None:
    results = asyncio.run(run_benchmark())
    assert results["two_calls"]["speedup"] > 1.3
    assert results["three_calls"]["speedup"] > 2.0
    assert results["error_isolation"]["timeout_tool_code"] == "TOOL_TIMEOUT"
    assert results["error_isolation"]["instant_tool_success"] is True
    assert results["compaction"]["tokens_reduction_pct"] > 40.0


if __name__ == "__main__":
    out = asyncio.run(run_benchmark())
    print("\n" + "=" * 60)
    print(" DRAGBIZZ BRAIN — PHASE B PERFORMANCE BENCHMARK REPORT")
    print("=" * 60)
    print(f"Controlled Mock Handler Latency: {out['simulated_tool_delay_ms']} ms")
    print("\n1. Two Independent Read Calls:")
    print(f"   - Sequential: {out['two_calls']['sequential_elapsed_ms']} ms")
    print(f"   - Parallel:   {out['two_calls']['parallel_elapsed_ms']} ms")
    print(f"   - Speedup:    {out['two_calls']['speedup']}x")

    print("\n2. Three Independent Read Calls:")
    print(f"   - Sequential: {out['three_calls']['sequential_elapsed_ms']} ms")
    print(f"   - Parallel:   {out['three_calls']['parallel_elapsed_ms']} ms")
    print(f"   - Speedup:    {out['three_calls']['speedup']}x")

    err_iso = out["error_isolation"]
    print("\n3. Error & Timeout Isolation:")
    print(f"   - Timeout tool result: {err_iso['timeout_tool_code']}")
    print(f"   - Sibling tool result: success={err_iso['instant_tool_success']}")

    comp = out["compaction"]
    print("\n4. Tool Result Compaction:")
    print(f"   - Tool: {comp['tool']}")
    print(
        f"   - Bytes:  {comp['raw_bytes']}B -> {comp['compacted_bytes']}B "
        f"({comp['bytes_reduction_pct']}% reduction)"
    )
    print(
        f"   - Tokens: {comp['raw_tokens']} -> {comp['compacted_tokens']} "
        f"({comp['tokens_reduction_pct']}% reduction)"
    )
    print("=" * 60 + "\n")
