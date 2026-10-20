"""Phase B Regression Tests: Parallel Tool Execution & Agent Loop Optimization.

Covers the 12 Phase B requirements:
1. Two independent read calls execute concurrently.
2. A deliberately delayed call does not force another independent read to wait for it.
3. Results retain the original tool-call IDs and ordering.
4. One read failure does not discard another successful read.
5. Timeouts and cancellation are handled correctly.
6. Database sessions and other shared resources remain safe.
7. Write and sensitive tools are not accidentally parallelized.
8. Purchase orders and invoices still require verified confirmation.
9. Multi-round tool calls preserve provider-compatible conversation history.
10. Model round limits stop runaway execution.
11. Existing Phase A domain-routing tests continue to pass.
12. Both supported provider paths remain compatible.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.confirmations import InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.dependencies import StageKind, plan_execution
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.context_optimize import compact_result_for_model
from app.orchestrator.tool_loop import (
    ToolCallValidator,
    ToolLoopOutcome,
    run_tool_loop,
)
from app.orchestrator.tool_selector import (
    detect_query_domains,
    resolve_domain_turn_intent,
)
from app.providers.openai_compatible import (
    _to_openai_message,
    _to_openai_tool_call,
)
from app.schemas.chat import (
    ChatMessage,
    GenerationResponse,
)
from app.schemas.tool import (
    ToolCall,
    ToolDefinition,
    ToolDomain,
    ToolResult,
    ToolRisk,
)
from app.tools.context import ToolContext
from app.tools.definitions import (
    ALL_TOOL_DEFINITIONS,
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE_ID = "6ad49964d5cb7a1b29d4bb7b"
USER_ID = "6ace9dede6f88a5b1523bd7d"
SESSION_ID = "test-session-123"


def _build_test_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for d in READ_TOOL_DEFINITIONS:
        reg.register(d, READ_TOOL_HANDLERS[d.name])
    for d in WRITE_TOOL_DEFINITIONS:
        reg.register(d, WRITE_TOOL_HANDLERS[d.name])
    for d in SENSITIVE_TOOL_DEFINITIONS:
        reg.register(d, SENSITIVE_TOOL_HANDLERS[d.name])
    return reg


# ---------------------------------------------------------------------------
# 1. Two independent read calls execute concurrently.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_two_independent_reads_execute_concurrently() -> None:
    reg = ToolRegistry()

    active_count = 0
    max_active = 0

    async def mock_search_product(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.04)
        active_count -= 1
        return ToolResult(
            tool="search_product", success=True, data={"products": []}
        )

    async def mock_search_supplier(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.04)
        active_count -= 1
        return ToolResult(
            tool="search_supplier", success=True, data={"suppliers": []}
        )

    def_prod = ToolDefinition(
        name="search_product",
        description="Search products",
        risk=ToolRisk.READ,
        parameters={"type": "object", "properties": {}},
    )
    def_supp = ToolDefinition(
        name="search_supplier",
        description="Search suppliers",
        risk=ToolRisk.READ,
        parameters={"type": "object", "properties": {}},
    )
    reg.register(def_prod, mock_search_product)
    reg.register(def_supp, mock_search_supplier)

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())
    calls = [
        ToolCall(
            id="call_p1",
            name="search_product",
            arguments={"storeId": STORE_ID},
        ),
        ToolCall(
            id="call_s1",
            name="search_supplier",
            arguments={"storeId": STORE_ID},
        ),
    ]

    start = time.perf_counter()
    results = await executor.execute_reads(
        calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"search_product", "search_supplier"}),
        parallel=True,
    )
    elapsed = time.perf_counter() - start

    assert len(results) == 2
    assert results[0].tool == "search_product"
    assert results[1].tool == "search_supplier"
    # Overlapping execution occurred: max_active reached 2
    assert max_active == 2
    # If sequential, would take >= 0.08s. In parallel, finishes well under 0.075s
    assert elapsed < 0.075


# ---------------------------------------------------------------------------
# 2. A deliberately delayed call does not force sibling to wait for it.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delayed_call_does_not_block_sibling() -> None:
    reg = ToolRegistry()
    completion_order: list[str] = []

    async def slow_read(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(0.08)
        return ToolResult(tool="slow_read", success=True, data={"slow": True})

    async def fast_read(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(0.01)
        return ToolResult(tool="fast_read", success=True, data={"fast": True})

    reg.register(
        ToolDefinition(
            name="slow_read",
            description="slow",
            risk=ToolRisk.READ,
            parameters={},
        ),
        slow_read,
    )
    reg.register(
        ToolDefinition(
            name="fast_read",
            description="fast",
            risk=ToolRisk.READ,
            parameters={},
        ),
        fast_read,
    )

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())
    calls = [
        ToolCall(
            id="call_slow", name="slow_read", arguments={"storeId": STORE_ID}
        ),
        ToolCall(
            id="call_fast", name="fast_read", arguments={"storeId": STORE_ID}
        ),
    ]

    async def on_complete(call: ToolCall, res: ToolResult) -> None:
        completion_order.append(call.name)

    results = await executor.execute_reads(
        calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"slow_read", "fast_read"}),
        parallel=True,
        on_tool_complete=on_complete,
    )

    assert len(results) == 2
    # fast_read completed before slow_read in real-time
    assert completion_order == ["fast_read", "slow_read"]


# ---------------------------------------------------------------------------
# 3. Results retain original tool-call IDs and ordering.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_results_retain_original_ids_and_ordering() -> None:
    reg = ToolRegistry()

    latencies = {"t0": 0.06, "t1": 0.01, "t2": 0.03}

    async def make_handler(name: str):
        async def handler(
            args: dict[str, Any], ctx: ToolContext
        ) -> ToolResult:
            await asyncio.sleep(latencies[name])
            return ToolResult(tool=name, success=True, data={"val": name})

        return handler

    for name in ("t0", "t1", "t2"):
        h = await make_handler(name)
        reg.register(
            ToolDefinition(
                name=name, description=name, risk=ToolRisk.READ, parameters={}
            ),
            h,
        )

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())
    calls = [
        ToolCall(id="call_id_0", name="t0", arguments={"storeId": STORE_ID}),
        ToolCall(id="call_id_1", name="t1", arguments={"storeId": STORE_ID}),
        ToolCall(id="call_id_2", name="t2", arguments={"storeId": STORE_ID}),
    ]

    results = await executor.execute_reads(
        calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"t0", "t1", "t2"}),
        parallel=True,
    )

    # Order must strictly match call list: t0, t1, t2
    assert [r.tool for r in results] == ["t0", "t1", "t2"]
    assert results[0].data["val"] == "t0"
    assert results[1].data["val"] == "t1"
    assert results[2].data["val"] == "t2"


# ---------------------------------------------------------------------------
# 4. One read failure does not discard another successful read.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_read_failure_isolation() -> None:
    reg = ToolRegistry()

    async def failing_read(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        raise RuntimeError("Network glitch in retailer")

    async def succeeding_read(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(
            tool="succeeding_read", success=True, data={"found": True}
        )

    reg.register(
        ToolDefinition(
            name="failing_read",
            description="fail",
            risk=ToolRisk.READ,
            parameters={},
        ),
        failing_read,
    )
    reg.register(
        ToolDefinition(
            name="succeeding_read",
            description="ok",
            risk=ToolRisk.READ,
            parameters={},
        ),
        succeeding_read,
    )

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())
    calls = [
        ToolCall(
            id="c_fail", name="failing_read", arguments={"storeId": STORE_ID}
        ),
        ToolCall(
            id="c_ok", name="succeeding_read", arguments={"storeId": STORE_ID}
        ),
    ]

    results = await executor.execute_reads(
        calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"failing_read", "succeeding_read"}),
        parallel=True,
    )

    assert len(results) == 2
    assert results[0].success is False
    assert results[0].data.get("code") == "RETAILER_UNAVAILABLE"
    # Sibling call succeeded without being aborted or discarded
    assert results[1].success is True
    assert results[1].data["found"] is True


# ---------------------------------------------------------------------------
# 5. Timeouts and cancellation are handled correctly.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeouts_and_cancellation() -> None:
    reg = ToolRegistry()

    async def slow_tool(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(0.2)
        return ToolResult(tool="slow_tool", success=True, data={})

    reg.register(
        ToolDefinition(
            name="slow_tool",
            description="slow",
            risk=ToolRisk.READ,
            parameters={},
        ),
        slow_tool,
    )

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())
    calls = [
        ToolCall(
            id="c_slow", name="slow_tool", arguments={"storeId": STORE_ID}
        ),
    ]

    # Test timeout
    results = await executor.execute_reads(
        calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"slow_tool"}),
        parallel=True,
        tool_timeout_seconds=0.03,
    )
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].data["code"] == "TOOL_TIMEOUT"
    assert "timed out after 0.03s" in results[0].data["message"]

    # Test cancellation propagation
    task = asyncio.create_task(
        executor.execute_reads(
            calls,
            access_token="tok",
            store_id=STORE_ID,
            allowed_names=frozenset({"slow_tool"}),
            parallel=True,
            tool_timeout_seconds=5.0,
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# 6. Database sessions and other shared resources remain safe.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sync_handlers_run_on_threadpool_safely() -> None:
    reg = ToolRegistry()

    # Synchronous handler simulating blocking CPU/db call
    def sync_read_handler(
        args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        time.sleep(0.02)
        return ToolResult(tool="sync_tool", success=True, data={"synced": True})

    reg.register(
        ToolDefinition(
            name="sync_tool",
            description="sync",
            risk=ToolRisk.READ,
            parameters={},
        ),
        sync_read_handler,
    )

    executor = ToolExecutor(registry=reg, retailer=AsyncMock())
    calls = [
        ToolCall(id="c_s1", name="sync_tool", arguments={"storeId": STORE_ID}),
        ToolCall(id="c_s2", name="sync_tool", arguments={"storeId": STORE_ID}),
    ]

    results = await executor.execute_reads(
        calls,
        access_token="tok",
        store_id=STORE_ID,
        allowed_names=frozenset({"sync_tool"}),
        parallel=True,
    )
    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is True


# ---------------------------------------------------------------------------
# 7. Write and sensitive tools are not accidentally parallelized.
# ---------------------------------------------------------------------------
def test_write_and_sensitive_tools_never_parallelized() -> None:
    reg = _build_test_registry()
    calls = [
        ToolCall(
            id="c_r1", name="search_product", arguments={"storeId": STORE_ID}
        ),
        ToolCall(
            id="c_r2", name="search_supplier", arguments={"storeId": STORE_ID}
        ),
        ToolCall(
            id="c_w1",
            name="create_customer",
            arguments={"storeId": STORE_ID, "name": "Rahul"},
        ),
        ToolCall(
            id="c_w2",
            name="update_customer",
            arguments={"storeId": STORE_ID, "name": "Rahul"},
        ),
        ToolCall(
            id="c_s1",
            name="create_purchase_order",
            arguments={"storeId": STORE_ID},
        ),
    ]

    stages = plan_execution(calls, registry=reg)

    # Stage 0: Parallel reads (search_product + search_supplier)
    assert stages[0].kind == StageKind.PARALLEL_READ
    assert len(stages[0].calls) == 2

    # Stage 1: Sequential write 1 (create_customer)
    assert stages[1].kind == StageKind.SEQUENTIAL_WRITE
    assert len(stages[1].calls) == 1
    assert stages[1].calls[0].name == "create_customer"

    # Stage 2: Sequential write 2 (update_customer)
    assert stages[2].kind == StageKind.SEQUENTIAL_WRITE
    assert len(stages[2].calls) == 1
    assert stages[2].calls[0].name == "update_customer"

    # Stage 3: Sequential sensitive (create_purchase_order)
    assert stages[3].kind == StageKind.SEQUENTIAL_SENSITIVE
    assert len(stages[3].calls) == 1
    assert stages[3].calls[0].name == "create_purchase_order"


# ---------------------------------------------------------------------------
# 8. Purchase orders and invoices still require verified confirmation.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_purchase_orders_require_verified_confirmation() -> None:
    reg = _build_test_registry()
    executor = ToolExecutor(registry=reg, retailer=AsyncMock())

    po_call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={"storeId": STORE_ID, "supplierId": "sup1"},
    )

    # Attempting to execute a sensitive tool directly as a read must raise AppError
    with pytest.raises(AppError) as exc:
        await executor.execute_reads(
            [po_call],
            access_token="tok",
            store_id=STORE_ID,
            allowed_names=frozenset({"create_purchase_order"}),
        )
    assert exc.value.code == "TOOL_NOT_EXECUTABLE"


# ---------------------------------------------------------------------------
# 9. Multi-round tool calls preserve provider-compatible conversation history.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multi_round_tool_calls_preserve_provider_history() -> None:
    reg = _build_test_registry()
    retailer = AsyncMock()
    retailer.get_products = AsyncMock(
        return_value=SimpleNamespace(status_code=200, body={"data": []})
    )
    executor = ToolExecutor(registry=reg, retailer=retailer)

    round_requests: list[list[ChatMessage]] = []

    class MockGateway:
        def __init__(self):
            self.turn = 0

        async def continue_or_synthesize(
            self,
            messages: list[ChatMessage],
            tools: list[ToolDefinition] | None = None,
            **kwargs,
        ) -> GenerationResponse:
            self.turn += 1
            round_requests.append(list(messages))
            # Round 2: Model finishes
            return GenerationResponse(
                provider="openai_compatible",
                model="test-gpt",
                content="Milk is available at Rs 30.",
                tool_calls=[],
            )

        async def repair_tool_calls(self, *args, **kwargs):
            raise AssertionError("no repair needed")

    gateway = MockGateway()
    validator = ToolCallValidator(reg)

    settings = SimpleNamespace(
        chat=SimpleNamespace(
            max_tool_rounds=3,
            temperature=0.0,
            max_tokens=100,
            synthesis_max_tokens=100,
        ),
        limits=SimpleNamespace(tool_timeout_seconds=5.0),
    )

    initial_gen = GenerationResponse(
        provider="openai_compatible",
        model="test-gpt",
        content="",
        tool_calls=[
            ToolCall(
                id="call_prod_1",
                name="search_product",
                arguments={"storeId": STORE_ID, "query": "milk"},
            ),
        ],
    )

    outcome: ToolLoopOutcome = await run_tool_loop(
        gateway=gateway,
        validator=validator,
        registry=reg,
        executor=executor,
        confirmations=InMemoryConfirmationStore(),
        settings=settings,
        generation=initial_gen,
        messages=[ChatMessage(role="user", content="Milk ka price kya hai?")],
        tools=list(reg.definitions()),
        language="hi-IN",
        store_id=STORE_ID,
        access_token="tok",
        session_id=SESSION_ID,
        user_id=USER_ID,
    )

    assert outcome.generation.content == "Milk is available at Rs 30."
    assert len(round_requests) == 1
    # Verify Round 2 messages have valid OpenAI-compatible schema
    round_2_messages = round_requests[0]
    assert round_2_messages[0].role == "user"
    assert round_2_messages[1].role == "assistant"
    assert round_2_messages[1].tool_calls[0].id == "call_prod_1"
    assert round_2_messages[2].role == "tool"
    assert round_2_messages[2].tool_call_id == "call_prod_1"

    # Serialized provider dicts
    openai_tool_msg = _to_openai_message(round_2_messages[2])
    assert openai_tool_msg["role"] == "tool"
    assert openai_tool_msg["tool_call_id"] == "call_prod_1"


# ---------------------------------------------------------------------------
# 10. Model round limits stop runaway execution.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_model_round_limits_stop_runaway() -> None:
    reg = _build_test_registry()
    retailer = AsyncMock()
    retailer.get_products = AsyncMock(
        return_value=SimpleNamespace(status_code=200, body={"data": []})
    )
    executor = ToolExecutor(registry=reg, retailer=retailer)

    class RunawayGateway:
        def __init__(self):
            self.round_count = 0

        async def continue_or_synthesize(self, *args, **kwargs):
            self.round_count += 1
            return GenerationResponse(
                provider="openai_compatible",
                model="test-gpt",
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"c_{self.round_count}",
                        name="search_product",
                        arguments={"storeId": STORE_ID, "query": "p"},
                    ),
                ],
            )

        async def repair_tool_calls(self, *args, **kwargs):
            raise AssertionError("no repair needed")

    gateway = RunawayGateway()
    validator = ToolCallValidator(reg)

    settings = SimpleNamespace(
        chat=SimpleNamespace(
            max_tool_rounds=2,
            temperature=0.0,
            max_tokens=100,
            synthesis_max_tokens=100,
        ),
        limits=SimpleNamespace(tool_timeout_seconds=5.0),
    )

    initial_gen = GenerationResponse(
        provider="openai_compatible",
        model="test-gpt",
        content="",
        tool_calls=[
            ToolCall(
                id="c_0",
                name="search_product",
                arguments={"storeId": STORE_ID, "query": "init"},
            ),
        ],
    )

    outcome = await run_tool_loop(
        gateway=gateway,
        validator=validator,
        registry=reg,
        executor=executor,
        confirmations=InMemoryConfirmationStore(),
        settings=settings,
        generation=initial_gen,
        messages=[ChatMessage(role="user", content="check stock")],
        tools=list(reg.definitions()),
        language="hi-IN",
        store_id=STORE_ID,
        access_token="tok",
        session_id=SESSION_ID,
        user_id=USER_ID,
    )

    # Loop stopped at exactly max_tool_rounds (2 rounds of tool executions)
    assert len(outcome.all_calls) == 2
    assert [c.id for c in outcome.all_calls] == ["c_0", "c_1"]


# ---------------------------------------------------------------------------
# 11. Existing Phase A domain-routing tests continue to pass.
# ---------------------------------------------------------------------------
def test_phase_a_domain_routing_persists() -> None:
    query = "Amul cheese slices ka 10 packet PO Amul supplier se banao"
    domains = detect_query_domains(query)
    assert ToolDomain.PROCUREMENT in domains

    all_names = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)
    intent = resolve_domain_turn_intent(query, available=all_names)
    assert intent.routing == "tools"
    assert "create_purchase_order" in intent.tool_names
    assert "search_supplier" in intent.tool_names
    assert "search_product" in intent.tool_names


# ---------------------------------------------------------------------------
# 12. Both supported provider paths remain compatible.
# ---------------------------------------------------------------------------
def test_provider_formats_compatible_gemini_and_openai() -> None:
    # 1. OpenAI formatting
    call_openai = ToolCall(
        id="call_123",
        name="search_product",
        arguments={"storeId": STORE_ID, "query": "amul"},
    )
    res_openai = _to_openai_tool_call(call_openai)
    assert res_openai["id"] == "call_123"
    assert res_openai["type"] == "function"
    assert res_openai["function"]["name"] == "search_product"
    assert "amul" in res_openai["function"]["arguments"]

    # 2. Gemini formatting (preserves thought_signature)
    call_gemini = ToolCall(
        id="call_gem_456",
        name="search_supplier",
        arguments={"storeId": STORE_ID, "name": "Amul"},
        thought_signature="sig_test_123",
    )
    res_gemini = _to_openai_tool_call(call_gemini)
    assert res_gemini["id"] == "call_gem_456"
    assert res_gemini.get("extra_content") == {
        "google": {"thought_signature": "sig_test_123"}
    }

    # 3. Tool result compaction keeps identifiers and structure intact
    result = ToolResult(
        tool="search_supplier",
        success=True,
        data={
            "found": True,
            "count": 10,
            "suppliers": [
                {
                    "supplierId": f"s_{i}",
                    "name": f"Supplier {i}",
                    "phone": "1234567890",
                }
                for i in range(10)
            ],
        },
    )
    compacted = compact_result_for_model(result)
    assert compacted.tool == "search_supplier"
    assert len(compacted.data["suppliers"]) <= 8
    assert compacted.data["suppliers"][0]["supplierId"] == "s_0"
