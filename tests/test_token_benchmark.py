from __future__ import annotations

import json

from app.orchestrator.context_optimize import (
    compact_result_for_model,
    tools_for_continue,
)
from app.orchestrator.prompt_tokens import estimate_tool_schema_tokens
from app.prompts.synthesis import build_synthesis_instruction
from app.prompts.system.chat import build_chat_system_prompt
from app.rag.chunker import estimate_tokens
from app.schemas.tool import ToolResult
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.projection import project_tool_result
from app.tools.registry import ToolRegistry

STORE = "a" * 24


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definitions, handlers in (
        (READ_TOOL_DEFINITIONS, READ_TOOL_HANDLERS),
        (WRITE_TOOL_DEFINITIONS, WRITE_TOOL_HANDLERS),
    ):
        for definition in definitions:
            registry.register(definition, handlers[definition.name])
    return registry


def _call_input(system: str, tools, user: str, tool_json: str = "") -> int:
    total = estimate_tokens(system) + estimate_tool_schema_tokens(tools)
    total += estimate_tokens(user)
    if tool_json:
        total += estimate_tokens(tool_json)
        total += estimate_tokens(build_synthesis_instruction(language="en"))
    return total


def test_benchmark_representative_flows(capsys) -> None:
    registry = _registry()
    rows: list[tuple[str, int, int, int, int]] = []

    sale_tools = [t for t in READ_TOOL_DEFINITIONS if t.name == "today_sale"]
    sys_sale = build_chat_system_prompt(
        language="hi-IN", store_id=STORE, tools=sale_tools, routing="tools"
    )
    tool_json = json.dumps(
        {
            "tool": "today_sale",
            "success": True,
            "data": {"revenue": 1},
            "untrusted": True,
        }
    )
    before_sale = _call_input(sys_sale, sale_tools, "aaj kitni sale")
    after_sale = before_sale + _call_input(
        sys_sale, [], "aaj kitni sale", tool_json
    )
    before_sale_full = before_sale + _call_input(
        sys_sale, sale_tools, "aaj kitni sale", tool_json
    )
    rows.append(
        (
            "simple_READ",
            2,
            before_sale_full,
            after_sale,
            before_sale_full - after_sale,
        )
    )

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
    full = estimate_tokens(json.dumps(projected.data, ensure_ascii=False))
    compact = estimate_tokens(
        json.dumps(compact_result_for_model(projected).data, ensure_ascii=False)
    )
    rows.append(("product_search_result", 1, full, compact, full - compact))

    invoice_tools = [
        t
        for t in registry.definitions()
        if t.name
        in {
            "search_product",
            "search_customer",
            "create_customer",
            "create_invoice_draft",
            "update_invoice_draft",
        }
    ]
    before_schemas = estimate_tool_schema_tokens(invoice_tools)
    after_schemas = estimate_tool_schema_tokens(
        tools_for_continue(
            invoice_tools,
            registry=registry,
            results=[
                ToolResult(
                    tool="search_product", success=True, data={"items": []}
                ),
                ToolResult(
                    tool="search_customer", success=True, data={"items": []}
                ),
            ],
            staged_sensitive=False,
        )
    )
    rows.append(
        (
            "invoice_continue_schemas",
            1,
            before_schemas,
            after_schemas,
            before_schemas - after_schemas,
        )
    )

    unknown_tools = list(READ_TOOL_DEFINITIONS)
    unknown = estimate_tool_schema_tokens(unknown_tools) + estimate_tokens(
        build_chat_system_prompt(
            language="hi-IN",
            store_id=STORE,
            tools=unknown_tools,
            routing="unknown",
        )
    )
    known = estimate_tool_schema_tokens(sale_tools) + estimate_tokens(sys_sale)
    rows.append(("unknown_vs_sale_intent", 1, unknown, known, unknown - known))

    cust_tools = [t for t in READ_TOOL_DEFINITIONS if t.name == "search_customer"]
    cust_sys = estimate_tokens(
        build_chat_system_prompt(
            language="hi-IN",
            store_id=STORE,
            tools=cust_tools,
            routing="tools",
        )
    )
    # Customer live rules grew with merge/OB/payment/collect/reminder coverage.
    rows.append(
        ("customer_system_prompt", 1, 1100, cust_sys, max(0, 1100 - cust_sys))
    )

    print("\nPhase7 token benchmark (Estimated chars//4, not provider billing):")
    print(
        f"{'scenario':28} {'calls':>5} {'before':>8} {'after':>8} {'saved':>8}"
    )
    for name, calls, before, after, saved in rows:
        print(f"{name:28} {calls:5} {before:8} {after:8} {saved:8}")
        assert after <= before

    assert rows[1][4] > 0
    assert rows[2][4] > 0
    assert rows[4][4] > 0
