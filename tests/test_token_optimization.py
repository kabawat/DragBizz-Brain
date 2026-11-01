"""Phase 7: token accounting, schema narrowing, model-facing compaction."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.confirmations import InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerResponse
from app.observability.metrics import MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.context_optimize import (
    compact_conversation_for_next_round,
    compact_result_for_model,
    tools_for_continue,
)
from app.orchestrator.prompt_tokens import estimate_tool_schema_tokens
from app.orchestrator.token_usage import RequestTokenUsage
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_loop import run_tool_loop
from app.prompts.system.chat import (
    build_chat_system_prompt,
    build_documentation_block,
)
from app.rag.chunker import estimate_tokens
from app.rag.models import RetrievedChunk
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolResult
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.projection import project_tool_result
from app.tools.registry import ToolRegistry

STORE = "a" * 24


class FakeProvider:
    name = "test_provider"

    def __init__(self, *, with_usage: bool = True) -> None:
        self.with_usage = with_usage
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls += 1
        return GenerationResponse(
            provider=self.name,
            model=request.model or "m",
            content="ok",
            tool_calls=[],
            input_tokens=100 if self.with_usage else None,
            output_tokens=20 if self.with_usage else None,
        )


class Router:
    def __init__(self, provider: FakeProvider) -> None:
        self._provider = provider

    def get(self, _name: str):
        return self._provider

    def get_active(self):
        return self._provider


def _registry(*, writes: bool = False) -> ToolRegistry:
    registry = ToolRegistry()
    groups = [(READ_TOOL_DEFINITIONS, READ_TOOL_HANDLERS)]
    if writes:
        groups.append((WRITE_TOOL_DEFINITIONS, WRITE_TOOL_HANDLERS))
    for definitions, handlers in groups:
        for definition in definitions:
            registry.register(definition, handlers[definition.name])
    return registry


def test_token_usage_actual_aggregation() -> None:
    asyncio.run(_actual_agg())


async def _actual_agg() -> None:
    gateway = AiGateway(Router(FakeProvider(with_usage=True)))
    usage = RequestTokenUsage()
    await gateway.generate_chat_turn(
        [ChatMessage(role="user", content="hi")],
        [],
        temperature=0.0,
        max_tokens=32,
        token_usage=usage,
        call_type="initial",
        round=0,
    )
    await gateway.continue_or_synthesize(
        [ChatMessage(role="user", content="hi")],
        [],
        language="en",
        allow_tools=False,
        temperature=0.0,
        max_tokens=32,
        token_usage=usage,
        round=1,
    )
    assert usage.model_calls == 2
    assert usage.input_tokens == 200
    assert usage.output_tokens == 40
    assert usage.total_tokens == 240
    assert usage.usage_source == "actual"
    assert usage.calls[1].call_type == "synthesize"


def test_token_usage_missing_is_unavailable() -> None:
    asyncio.run(_missing())


async def _missing() -> None:
    gateway = AiGateway(Router(FakeProvider(with_usage=False)))
    usage = RequestTokenUsage()
    await gateway.generate_chat_turn(
        [ChatMessage(role="user", content="hi")],
        [],
        temperature=0.0,
        max_tokens=32,
        token_usage=usage,
    )
    assert usage.usage_source == "unavailable"
    assert usage.total_tokens is None


def test_retry_recorded() -> None:
    asyncio.run(_retry())


async def _retry() -> None:
    class Flaky(FakeProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResponse:
            if self.calls == 0:
                self.calls += 1
                raise AppError(
                    code="AI_PROVIDER_ERROR",
                    message="down",
                    status_code=502,
                    retryable=True,
                )
            return await super().generate(request)

    primary = Flaky(with_usage=True)
    primary.name = "openai_compatible"

    class SingleRouter:
        def get(self, name: str):
            return primary if name == "openai_compatible" else None

        def get_active(self):
            return primary

    usage = RequestTokenUsage()
    await AiGateway(SingleRouter()).generate(
        GenerationRequest(messages=[ChatMessage(role="user", content="x")]),
        token_usage=usage,
        call_type="initial",
    )
    assert usage.model_calls == 1
    assert usage.calls[0].retry is True
    assert primary.calls == 2


def test_tools_for_continue_drops_draft_after_success() -> None:
    registry = _registry(writes=True)
    tools = [
        t
        for t in registry.definitions()
        if t.name
        in {
            "search_product",
            "search_customer",
            "create_invoice_draft",
            "create_customer",
        }
    ]
    narrowed = tools_for_continue(
        tools,
        registry=registry,
        results=[
            ToolResult(
                tool="create_invoice_draft", success=True, data={"id": "x"}
            ),
        ],
        staged_sensitive=False,
    )
    names = {t.name for t in narrowed}
    assert "create_invoice_draft" not in names
    assert "create_customer" not in names


def test_tools_for_continue_narrows_after_searches() -> None:
    registry = _registry(writes=True)
    wide = [
        t
        for t in registry.definitions()
        if t.name
        in {
            "search_product",
            "search_customer",
            "today_sale",
            "create_invoice_draft",
        }
    ]
    narrow = tools_for_continue(
        wide,
        registry=registry,
        results=[
            ToolResult(tool="search_product", success=True, data={"items": []}),
            ToolResult(tool="search_customer", success=True, data={"items": []}),
        ],
        staged_sensitive=False,
    )
    names = {t.name for t in narrow}
    assert "create_invoice_draft" in names
    assert "today_sale" not in names
    assert estimate_tool_schema_tokens(narrow) < estimate_tool_schema_tokens(wide)


def test_final_synthesis_has_no_tools() -> None:
    asyncio.run(_synth_no_tools())


async def _synth_no_tools() -> None:
    captured: list[GenerationRequest] = []

    class Capturing(FakeProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResponse:
            captured.append(request)
            return await super().generate(request)

    await AiGateway(Router(Capturing())).continue_or_synthesize(
        [ChatMessage(role="user", content="hi")],
        list(READ_TOOL_DEFINITIONS),
        language="en",
        allow_tools=False,
        temperature=0.0,
        max_tokens=32,
    )
    assert captured[0].tools is None
    assert captured[0].tool_choice == "none"


def test_compact_result_for_model_truncates_lists() -> None:
    items = [
        {
            "id": "b" * 24,
            "name": f"P{i}",
            "sku": f"S{i}",
            "sellingPrice": i,
            "stock": 1,
            "taxRate": 18,
            "unit": "pcs",
            "status": "ACTIVE",
        }
        for i in range(20)
    ]
    projected = project_tool_result(
        ToolResult(tool="search_product", success=True, data={"items": items})
    )
    assert len(projected.data["items"]) == 20
    model = compact_result_for_model(projected)
    assert len(model.data["items"]) == 8
    assert model.data.get("truncated") is True


def test_conversation_strips_documentation() -> None:
    system = build_chat_system_prompt(
        language="en",
        store_id=STORE,
        tools=[],
        documentation=("How to create an invoice. " * 40),
        routing="docs",
    )
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="how to bill"),
    ]
    before = estimate_tokens(system)
    out, removed = compact_conversation_for_next_round(messages)
    assert removed > 0
    assert "Documentation:\nHow to" not in out[0].content
    assert estimate_tokens(out[0].content) < before


def test_rag_dedupes_identical_chunks() -> None:
    text = "Same FAQ answer about GST."
    chunks = [
        RetrievedChunk(
            id="1", text=text, metadata={"source": "faq.md"}, score=0.9
        ),
        RetrievedChunk(
            id="2", text=text, metadata={"source": "faq.md"}, score=0.8
        ),
    ]
    block = build_documentation_block(chunks, max_tokens=500)
    assert block.count("Same FAQ answer") == 1


def test_metrics_token_snapshot() -> None:
    metrics = MetricsRegistry()
    metrics.record_token_usage(
        input_tokens=10, output_tokens=5, usage_source="actual"
    )
    metrics.record_compaction(compacted=3, removed_schemas=2, removed_results=1)
    snap = metrics.snapshot()
    assert snap["tokens"]["total"] == 15
    assert snap["tokens"]["actualCalls"] == 1
    assert snap["context"]["compacted"] == 3


def test_tool_loop_model_messages_use_compacted_results() -> None:
    asyncio.run(_loop_compact())


async def _loop_compact() -> None:
    registry = _registry()

    class Retailer:
        async def get_products(self, **kwargs):
            return RetailerResponse(
                status_code=200,
                body={
                    "data": [
                        {
                            "id": "b" * 24,
                            "name": f"P{i}",
                            "sku": f"S{i}",
                            "pricing": {"sellingPrice": i, "uom": "pcs"},
                            "stock": 1,
                            "status": "ACTIVE",
                        }
                        for i in range(20)
                    ]
                },
            )

    class Gateway:
        def __init__(self) -> None:
            self.saw_compacted = False

        async def continue_or_synthesize(self, conversation, tools, **kwargs):
            for message in conversation:
                if message.role == "tool":
                    payload = json.loads(message.content)
                    items = (payload.get("data") or {}).get("items") or []
                    assert len(items) <= 8
                    self.saw_compacted = True
            return GenerationResponse(
                provider="t", model="m", content="done", tool_calls=[]
            )

        async def repair_tool_calls(self, *_a, **_k):
            raise AssertionError("no repair")

    gateway = Gateway()
    await run_tool_loop(
        gateway=gateway,
        validator=ToolCallValidator(registry),
        registry=registry,
        executor=ToolExecutor(registry=registry, retailer=Retailer()),
        confirmations=InMemoryConfirmationStore(),
        settings=SimpleNamespace(
            chat=SimpleNamespace(
                max_tool_rounds=2,
                temperature=0.0,
                max_tokens=64,
                synthesis_max_tokens=64,
            )
        ),
        generation=GenerationResponse(
            provider="t",
            model="m",
            content="",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="search_product",
                    arguments={"storeId": STORE, "query": "maggi"},
                )
            ],
        ),
        messages=[],
        tools=list(READ_TOOL_DEFINITIONS),
        language="en",
        store_id=STORE,
        access_token="t",
        session_id="s",
        user_id="u",
    )
    assert gateway.saw_compacted is True
