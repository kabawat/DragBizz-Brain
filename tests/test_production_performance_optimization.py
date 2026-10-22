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
from app.orchestrator.tool_loop import ToolCallValidator, run_tool_loop
from app.orchestrator.tool_selector import (
    SAFE_BROAD_STORE_FALLBACK,
    detect_query_domains,
    resolve_domain_turn_intent,
)
from app.providers.openai_compatible import _to_openai_tool_call
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import (
    ToolCall,
    ToolDefinition,
    ToolDomain,
    ToolResult,
    ToolRisk,
)
from app.tools.context import ToolContext
from app.tools.definitions import ALL_TOOL_DEFINITIONS
from app.tools.registry import ToolRegistry


STORE_A = "6ad49964d5cb7a1b29d4bb7b"
STORE_B = "6ad49964d5cb7a1b29d4bb7c"
USER_1 = "6ace9dede6f88a5b1523bd7d"
USER_2 = "6ace9dede6f88a5b1523bd7e"
SESSION_1 = "test-session-1"
SESSION_2 = "test-session-2"


def _make_settings(max_rounds: int = 3) -> Any:
    return SimpleNamespace(
        chat=SimpleNamespace(
            max_tool_rounds=max_rounds,
            temperature=0.0,
            max_tokens=100,
            synthesis_max_tokens=100,
        ),
        limits=SimpleNamespace(tool_timeout_seconds=5.0),
    )


def test_scenario_1_sales_query_selects_minimal_tools_and_no_writes() -> None:
    available = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)
    intent = resolve_domain_turn_intent("aaj ki sales kitni hui", available=available)
    assert intent.routing == "tools"
    assert "today_sale" in intent.tool_names or "invoice_summary" in intent.tool_names
    assert "create_invoice_draft" not in intent.tool_names
    assert "ledger_debit" not in intent.tool_names
    assert len(intent.tool_names) < len(available)


def test_scenario_2_inventory_query_excludes_irrelevant_schemas() -> None:
    available = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)
    intent = resolve_domain_turn_intent("stock check karo maggi ka", available=available)
    assert intent.routing == "tools"
    assert "stock_summary" in intent.tool_names or "search_product" in intent.tool_names
    assert "today_sale" not in intent.tool_names
    assert "create_expense" not in intent.tool_names
    assert "create_invoice_draft" not in intent.tool_names


def test_scenario_3_cross_domain_query_retains_required_tools() -> None:
    available = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)
    intent = resolve_domain_turn_intent(
        "Amul supplier se 10 butter packet ka PO banao aur stock check karo",
        available=available,
    )
    assert intent.routing == "tools"
    assert "create_purchase_order" in intent.tool_names
    assert "search_supplier" in intent.tool_names
    assert "search_product" in intent.tool_names
    assert "stock_summary" in intent.tool_names


def test_scenario_4_ambiguous_query_safely_falls_back_read_only() -> None:
    available = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)
    intent = resolve_domain_turn_intent("xyz uncertain request 123", available=available)
    assert intent.routing == "unknown"
    assert intent.tool_names == (SAFE_BROAD_STORE_FALLBACK & available)
    reg = ToolRegistry()
    for d in ALL_TOOL_DEFINITIONS:
        reg.register(d, AsyncMock())
    for name in intent.tool_names:
        assert reg.get_definition(name).risk == ToolRisk.READ


@pytest.mark.asyncio
async def test_scenario_5_multiple_independent_tools_execute_concurrently() -> None:
    reg = ToolRegistry()
    active = 0
    max_active = 0

    async def h1(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return ToolResult(tool="t1", success=True, data={"v": 1})

    async def h2(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return ToolResult(tool="t2", success=True, data={"v": 2})

    d1 = ToolDefinition(name="t1", description="tool 1", domain=ToolDomain.SALES, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    d2 = ToolDefinition(name="t2", description="tool 2", domain=ToolDomain.SALES, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    reg.register(d1, h1)
    reg.register(d2, h2)

    executor = ToolExecutor(retailer=AsyncMock(), registry=reg)
    calls = [
        ToolCall(id="c1", name="t1", arguments={"storeId": STORE_A}),
        ToolCall(id="c2", name="t2", arguments={"storeId": STORE_A}),
    ]
    t0 = time.monotonic()
    results = await executor.execute_reads(calls, store_id=STORE_A, access_token="tok", allowed_names=frozenset({"t1", "t2"}), parallel=True)
    duration = time.monotonic() - t0
    assert max_active == 2
    assert duration < 0.09
    assert len(results) == 2
    assert results[0].tool == "t1"
    assert results[1].tool == "t2"


def test_scenario_6_dependent_tool_calls_execute_in_correct_stages() -> None:
    reg = ToolRegistry()
    d_read1 = ToolDefinition(name="search_product", description="search prod", domain=ToolDomain.INVENTORY, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    d_read2 = ToolDefinition(name="search_customer", description="search cust", domain=ToolDomain.KHATA, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    d_write = ToolDefinition(name="create_invoice_draft", description="create draft", domain=ToolDomain.SALES, risk=ToolRisk.WRITE, parameters={}, allows_parallel=False)
    reg.register(d_read1, AsyncMock())
    reg.register(d_read2, AsyncMock())
    reg.register(d_write, AsyncMock())

    calls = [
        ToolCall(id="c1", name="search_product", arguments={}),
        ToolCall(id="c2", name="search_customer", arguments={}),
        ToolCall(id="c3", name="create_invoice_draft", arguments={}),
    ]
    stages = plan_execution(calls, registry=reg)
    assert len(stages) == 2
    assert stages[0].kind == StageKind.PARALLEL_READ
    assert {c.id for c in stages[0].calls} == {"c1", "c2"}
    assert stages[1].kind == StageKind.SEQUENTIAL_WRITE
    assert [c.id for c in stages[1].calls] == ["c3"]


@pytest.mark.asyncio
async def test_scenario_7_failing_tool_does_not_invalidate_sibling_results() -> None:
    reg = ToolRegistry()

    async def fail_handler(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise ValueError("simulated network failure")

    async def ok_handler(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(tool="search_product", success=True, data={"products": ["item1"]})

    d_fail = ToolDefinition(name="search_supplier", description="search sup", domain=ToolDomain.PROCUREMENT, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    d_ok = ToolDefinition(name="search_product", description="search prod", domain=ToolDomain.INVENTORY, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    reg.register(d_fail, fail_handler)
    reg.register(d_ok, ok_handler)

    executor = ToolExecutor(retailer=AsyncMock(), registry=reg)
    calls = [
        ToolCall(id="c1", name="search_supplier", arguments={"storeId": STORE_A}),
        ToolCall(id="c2", name="search_product", arguments={"storeId": STORE_A}),
    ]
    results = await executor.execute_reads(calls, store_id=STORE_A, access_token="tok", allowed_names=frozenset({"search_supplier", "search_product"}), parallel=True)
    assert len(results) == 2
    assert results[0].success is False
    assert results[0].tool == "search_supplier"
    assert results[1].success is True
    assert results[1].tool == "search_product"
    assert results[1].data == {"products": ["item1"]}


def test_scenario_8_tool_call_ids_and_provider_format_compatibility() -> None:
    call = ToolCall(
        id="unique-call-id-99",
        name="today_sale",
        arguments={"storeId": STORE_A},
    )
    formatted = _to_openai_tool_call(call)
    assert formatted["id"] == "unique-call-id-99"
    assert formatted["type"] == "function"
    assert formatted["function"]["name"] == "today_sale"
    assert "storeId" in formatted["function"]["arguments"]


@pytest.mark.asyncio
async def test_scenario_9_streaming_emits_partial_text_before_completion() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    async def mock_emit(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    chunks = ["Aaj ", "ki ", "kul ", "bikri ", "Rs 5,000 ", "hai."]

    class StreamingGateway:
        async def continue_or_synthesize(self, *args: Any, **kwargs: Any) -> GenerationResponse:
            return GenerationResponse(
                provider="openai_compatible",
                model="gpt-4o",
                content="".join(chunks),
                tool_calls=[],
            )

        async def continue_or_synthesize_stream(self, *args: Any, **kwargs: Any):
            for c in chunks:
                await asyncio.sleep(0.01)
                yield c

    gateway = StreamingGateway()
    reg = ToolRegistry()
    def_read = ToolDefinition(name="today_sale", description="sales info", domain=ToolDomain.SALES, risk=ToolRisk.READ, parameters={})
    reg.register(def_read, AsyncMock(return_value=ToolResult(tool="today_sale", success=True, data={"total": 5000})))

    gen = GenerationResponse(
        provider="openai_compatible",
        model="gpt-4o",
        content="",
        tool_calls=[ToolCall(id="c1", name="today_sale", arguments={"storeId": STORE_A})],
    )
    settings = _make_settings(max_rounds=2)
    outcome = await run_tool_loop(
        gateway=gateway,
        validator=ToolCallValidator(reg),
        registry=reg,
        executor=ToolExecutor(retailer=AsyncMock(), registry=reg),
        confirmations=InMemoryConfirmationStore(),
        settings=settings,
        generation=gen,
        messages=[ChatMessage(role="user", content="sales batao")],
        tools=[def_read],
        language="hi-IN",
        store_id=STORE_A,
        access_token="tok",
        session_id=SESSION_1,
        user_id=USER_1,
        emit=mock_emit,
    )
    delta_texts = [d["text"] for ev, d in events if ev == "assistant.delta"]
    assert delta_texts == chunks
    assert outcome.generation.content == "".join(chunks)


@pytest.mark.asyncio
async def test_scenario_10_tool_execution_followed_by_stream_continues_same_stream() -> None:
    events: list[str] = []

    async def emit_listener(ev: str, data: dict[str, Any]) -> None:
        if ev == "tool.started":
            events.append(f"start:{data['tool']}")
        elif ev == "tool.completed":
            events.append(f"done:{data['tool']}")
        elif ev == "assistant.delta":
            events.append(f"text:{data['text']}")

    class MultiGateway:
        async def continue_or_synthesize(self, *args: Any, **kwargs: Any) -> GenerationResponse:
            return GenerationResponse(
                provider="openai_compatible",
                model="gpt-4o",
                content="Result: Success.",
                tool_calls=[],
            )

        async def continue_or_synthesize_stream(self, *args: Any, **kwargs: Any):
            yield "Result: "
            yield "Success."

    reg = ToolRegistry()
    def_read = ToolDefinition(name="stock_summary", description="stock info", domain=ToolDomain.INVENTORY, risk=ToolRisk.READ, parameters={})
    reg.register(def_read, AsyncMock(return_value=ToolResult(tool="stock_summary", success=True, data={"stock": 100})))

    gen = GenerationResponse(
        provider="openai_compatible",
        model="gpt-4o",
        content="",
        tool_calls=[ToolCall(id="c1", name="stock_summary", arguments={"storeId": STORE_A})],
    )
    outcome = await run_tool_loop(
        gateway=MultiGateway(),
        validator=ToolCallValidator(reg),
        registry=reg,
        executor=ToolExecutor(retailer=AsyncMock(), registry=reg),
        confirmations=InMemoryConfirmationStore(),
        settings=_make_settings(max_rounds=2),
        generation=gen,
        messages=[ChatMessage(role="user", content="stock")],
        tools=[def_read],
        language="hi-IN",
        store_id=STORE_A,
        access_token="tok",
        session_id=SESSION_1,
        user_id=USER_1,
        emit=emit_listener,
    )
    assert events == ["start:stock_summary", "done:stock_summary", "text:Result: ", "text:Success."]
    assert outcome.generation.content == "Result: Success."


@pytest.mark.asyncio
async def test_scenario_11_cancellation_cleans_up_without_resource_leaks() -> None:
    cancel_event = asyncio.Event()

    class CancellableCancel:
        def is_cancelled(self) -> bool:
            return cancel_event.is_set()

        def raise_if_cancelled(self) -> None:
            if self.is_cancelled():
                raise asyncio.CancelledError()

    cancel = CancellableCancel()
    cancel_event.set()

    reg = ToolRegistry()
    def_read = ToolDefinition(name="stock_summary", description="stock info", domain=ToolDomain.INVENTORY, risk=ToolRisk.READ, parameters={})
    reg.register(def_read, AsyncMock())

    gen = GenerationResponse(
        provider="openai_compatible",
        model="gpt-4o",
        content="",
        tool_calls=[ToolCall(id="c1", name="stock_summary", arguments={"storeId": STORE_A})],
    )
    with pytest.raises(asyncio.CancelledError):
        await run_tool_loop(
            gateway=AsyncMock(),
            validator=ToolCallValidator(reg),
            registry=reg,
            executor=ToolExecutor(retailer=AsyncMock(), registry=reg),
            confirmations=InMemoryConfirmationStore(),
            settings=_make_settings(),
            generation=gen,
            messages=[ChatMessage(role="user", content="stock")],
            tools=[def_read],
            language="hi-IN",
            store_id=STORE_A,
            access_token="tok",
            session_id=SESSION_1,
            user_id=USER_1,
            cancel=cancel,
        )


def test_scenario_12_tenant_isolation_and_cross_store_rejection() -> None:
    reg = ToolRegistry()
    def_write = ToolDefinition(name="create_expense", description="create expense", domain=ToolDomain.FINANCE, risk=ToolRisk.WRITE, parameters={})
    reg.register(def_write, AsyncMock())
    validator = ToolCallValidator(reg)

    bad_calls = [
        ToolCall(id="c1", name="create_expense", arguments={"storeId": STORE_B, "amount": 100}),
    ]
    with pytest.raises(AppError) as exc:
        validator.validate(bad_calls, allowed_names=frozenset({"create_expense"}), store_id=STORE_A)
    assert exc.value.code == "TOOL_ARGS_INVALID"


@pytest.mark.asyncio
async def test_scenario_13_concurrent_requests_remain_isolated() -> None:
    reg = ToolRegistry()

    async def mock_handler(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(0.02)
        return ToolResult(tool="search_product", success=True, data={"store": ctx.store_id, "token": ctx.access_token})

    def_tool = ToolDefinition(name="search_product", description="search prod", domain=ToolDomain.INVENTORY, risk=ToolRisk.READ, parameters={}, allows_parallel=True)
    reg.register(def_tool, mock_handler)
    executor = ToolExecutor(retailer=AsyncMock(), registry=reg)

    task_1 = executor.execute_reads(
        [ToolCall(id="c1", name="search_product", arguments={"storeId": STORE_A})],
        store_id=STORE_A,
        access_token="tok1",
        allowed_names=frozenset({"search_product"}),
    )
    task_2 = executor.execute_reads(
        [ToolCall(id="c2", name="search_product", arguments={"storeId": STORE_B})],
        store_id=STORE_B,
        access_token="tok2",
        allowed_names=frozenset({"search_product"}),
    )
    res1, res2 = await asyncio.gather(task_1, task_2)
    assert res1[0].data["store"] == STORE_A
    assert res1[0].data["token"] == "tok1"
    assert res2[0].data["store"] == STORE_B
    assert res2[0].data["token"] == "tok2"


@pytest.mark.asyncio
async def test_scenario_14_non_streaming_fallback_path_operates_correctly() -> None:
    class NonStreamingGateway:
        async def continue_or_synthesize(self, *args: Any, **kwargs: Any) -> GenerationResponse:
            return GenerationResponse(
                provider="openai_compatible",
                model="gpt-4o",
                content="Standard non-streaming reply",
                tool_calls=[],
            )

    reg = ToolRegistry()
    def_read = ToolDefinition(name="today_sale", description="sales info", domain=ToolDomain.SALES, risk=ToolRisk.READ, parameters={})
    reg.register(def_read, AsyncMock(return_value=ToolResult(tool="today_sale", success=True, data={"total": 100})))

    gen = GenerationResponse(
        provider="openai_compatible",
        model="gpt-4o",
        content="",
        tool_calls=[ToolCall(id="c1", name="today_sale", arguments={"storeId": STORE_A})],
    )
    outcome = await run_tool_loop(
        gateway=NonStreamingGateway(),
        validator=ToolCallValidator(reg),
        registry=reg,
        executor=ToolExecutor(retailer=AsyncMock(), registry=reg),
        confirmations=InMemoryConfirmationStore(),
        settings=_make_settings(max_rounds=2),
        generation=gen,
        messages=[ChatMessage(role="user", content="sales")],
        tools=[def_read],
        language="hi-IN",
        store_id=STORE_A,
        access_token="tok",
        session_id=SESSION_1,
        user_id=USER_1,
        emit=None,
    )
    assert outcome.generation.content == "Standard non-streaming reply"
    assert len(outcome.all_calls) == 1
