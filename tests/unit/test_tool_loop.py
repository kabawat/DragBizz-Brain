"""Unit tests for tool_loop partition / signature helpers."""

from __future__ import annotations
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.orchestrator.tool_loop import call_signature, partition_tool_calls
from app.schemas.tool import ToolCall
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.registry import ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    for definition in (
        *READ_TOOL_DEFINITIONS,
        *WRITE_TOOL_DEFINITIONS,
        *SENSITIVE_TOOL_DEFINITIONS,
    ):
        reg.register_definition(definition)
    return reg


def test_partition_tool_calls_by_risk(registry: ToolRegistry) -> None:
    calls = [
        ToolCall(id="1", name="today_sale", arguments={"storeId": "s"}),
        ToolCall(
            id="2",
            name="create_invoice_draft",
            arguments={"storeId": "s"},
        ),
        ToolCall(
            id="3",
            name="release_invoice",
            arguments={"storeId": "s", "invoiceId": "inv1"},
        ),
    ]
    reads, writes, sensitive = partition_tool_calls(calls, registry=registry)
    assert [c.name for c in reads] == ["today_sale"]
    assert [c.name for c in writes] == ["create_invoice_draft"]
    assert [c.name for c in sensitive] == ["release_invoice"]


def test_partition_rejects_unsupported_risk() -> None:
    class _Stub:
        def get_definition(self, name: str) -> SimpleNamespace:
            return SimpleNamespace(risk="unknown")

    with pytest.raises(AppError) as exc_info:
        partition_tool_calls(
            [ToolCall(id="1", name="weird_tool", arguments={})],
            registry=_Stub(),  # type: ignore[arg-type]
        )
    assert exc_info.value.code == "TOOL_NOT_EXECUTABLE"


def test_call_signature_stable_for_key_order() -> None:
    a = ToolCall(
        id="1",
        name="search_product",
        arguments={"storeId": "s", "query": "oil"},
    )
    b = ToolCall(
        id="2",
        name="search_product",
        arguments={"query": "oil", "storeId": "s"},
    )
    assert call_signature(a) == call_signature(b)
    assert call_signature(a)[0] == "search_product"
