"""Phase 2 result contracts distinguish data, empties, partials and failures."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.context_optimize import compact_result_for_model
from app.schemas.tool import (
    ToolCall,
    ToolDefinition,
    ToolEffectStatus,
    ToolResult,
    ToolResultStatus,
    ToolRetryPolicy,
    ToolRisk,
    ToolSideEffect,
)
from app.tools.context import ToolContext
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.projection import project_tool_result
from app.tools.registry import ToolRegistry


def test_result_status_distinguishes_empty_partial_and_failure() -> None:
    empty = ToolResult(
        tool="list_invoices", success=True, data={"items": [], "count": 0}
    )
    partial = ToolResult(
        tool="list_invoices",
        success=True,
        data={"items": [{"id": "i1"}], "count": 1, "hasMore": True},
    )
    failed = ToolResult(
        tool="list_invoices",
        success=False,
        data={"code": "RETAILER_UNAVAILABLE", "message": "unavailable"},
    )

    assert empty.result_status == ToolResultStatus.SUCCESS_EMPTY
    assert empty.returned_count == 0
    assert partial.result_status == ToolResultStatus.SUCCESS_PARTIAL
    assert partial.returned_count == 1
    assert failed.result_status == ToolResultStatus.DEPENDENCY_ERROR


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("TOOL_UNSUPPORTED", ToolResultStatus.UNSUPPORTED),
        ("TOOL_ARGS_INVALID", ToolResultStatus.INVALID_INPUT),
        ("TOOL_FORBIDDEN", ToolResultStatus.UNAUTHORIZED),
        ("TOOL_NOT_FOUND", ToolResultStatus.NOT_FOUND),
        ("TOOL_TIMEOUT", ToolResultStatus.TIMEOUT),
        ("INTERNAL_ERROR", ToolResultStatus.INTERNAL_ERROR),
    ],
)
def test_failure_codes_map_to_explicit_result_statuses(
    code: str, expected: ToolResultStatus
) -> None:
    result = ToolResult(tool="probe", success=False, data={"code": code})
    assert result.result_status == expected


def test_result_status_must_agree_with_success_and_metadata_is_typed() -> None:
    with pytest.raises(ValueError, match="success must agree"):
        ToolResult(
            tool="probe",
            success=False,
            result_status=ToolResultStatus.SUCCESS_WITH_DATA,
        )

    result = ToolResult(
        tool="list_invoices",
        success=True,
        data={
            "items": [{"id": "i1"}],
            "count": 1,
            "totalCount": 12,
            "filters": {"status": "UNPAID"},
            "pagination": {"hasMore": True, "page": 1, "page_size": 10},
            "asOf": "2026-10-25T00:00:00+05:30",
        },
    )
    serialized = result.model_dump(by_alias=True)
    assert serialized["returnedCount"] == 1
    assert serialized["totalCount"] == 12
    assert serialized["appliedFilters"] == {"status": "UNPAID"}
    assert serialized["pagination"]["hasMore"] is True
    assert serialized["sourceTimestamp"] == "2026-10-25T00:00:00+05:30"


def test_projection_preserves_result_contract() -> None:
    original = ToolResult(
        tool="list_invoices",
        success=True,
        data={"items": [{"id": "i1", "invoiceNumber": "INV-1"}], "count": 1},
        applied_filters={"status": "UNPAID"},
        total_count=4,
        source="retailer_api",
        correlation_id="req-test",
    )
    projected = project_tool_result(original)
    assert projected.result_status == original.result_status
    assert projected.applied_filters == original.applied_filters
    assert projected.total_count == original.total_count
    assert projected.source == original.source
    assert projected.correlation_id == original.correlation_id


def test_invoice_model_preview_preserves_source_status_and_discloses_truncation() -> None:
    result = ToolResult(
        tool="list_invoices",
        success=True,
        data={
            "count": 10,
            "invoices": [{"id": f"inv-{i}"} for i in range(10)],
        },
    )
    compacted = compact_result_for_model(result)

    assert compacted.result_status == ToolResultStatus.SUCCESS_WITH_DATA
    assert compacted.returned_count == 10
    assert compacted.total_count is None
    assert compacted.pagination is None
    assert compacted.data["previewCount"] == 8
    assert compacted.data["truncated"] is True


def test_invoice_model_preview_does_not_change_source_counts_or_pagination() -> None:
    result = ToolResult(
        tool="list_invoices",
        success=True,
        data={
            "count": 10,
            "invoices": [{"id": f"inv-{i}"} for i in range(10)],
            "pagination": {"hasMore": False, "pageSize": 10},
        },
        returned_count=10,
        pagination={"hasMore": False, "pageSize": 10},
    )

    compacted = compact_result_for_model(result)

    assert len(compacted.data["invoices"]) == 8
    assert compacted.data["count"] == 10
    assert compacted.data["previewCount"] == 8
    assert compacted.data["truncated"] is True
    assert compacted.result_status == ToolResultStatus.SUCCESS_WITH_DATA
    assert compacted.returned_count == 10
    assert compacted.total_count is None
    assert compacted.pagination.has_more is False


def test_every_registered_tool_has_side_effect_and_retry_classification() -> None:
    definitions = (
        *READ_TOOL_DEFINITIONS,
        *WRITE_TOOL_DEFINITIONS,
        *SENSITIVE_TOOL_DEFINITIONS,
    )
    for definition in definitions:
        assert definition.side_effect is not None
        assert definition.retry_policy is not None
        if definition.risk == ToolRisk.READ:
            assert definition.side_effect == ToolSideEffect.NONE
            assert definition.retry_policy == ToolRetryPolicy.SAFE_READ
        else:
            assert definition.retry_policy == ToolRetryPolicy.IDEMPOTENCY_KEY


@pytest.mark.asyncio
async def test_executor_converts_raised_handler_errors_to_typed_result() -> None:
    async def raises_forbidden(_arguments: dict[str, Any], _context: ToolContext):
        raise AppError("TOOL_FORBIDDEN", "No access", status_code=403)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="probe_read", description="Read probe", risk=ToolRisk.READ),
        raises_forbidden,
    )
    executor = ToolExecutor(registry=registry, retailer=object())
    result = (
        await executor.execute_reads(
            [ToolCall(id="call-1", name="probe_read")],
            access_token="token",
            store_id="store-1",
            allowed_names={"probe_read"},
        )
    )[0]

    assert result.success is False
    assert result.result_status == ToolResultStatus.UNAUTHORIZED
    assert result.data == {
        "code": "TOOL_FORBIDDEN",
        "message": "You do not have permission to complete this request.",
    }
    assert result.applied_filters == {"storeScoped": True}
    assert result.source == "retailer_api"


@pytest.mark.asyncio
async def test_executor_rejects_unstructured_empty_response() -> None:
    async def empty_response(_arguments: dict[str, Any], _context: ToolContext):
        return ToolResult(tool="probe_read", success=True, data={})

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="probe_read", description="Read probe", risk=ToolRisk.READ),
        empty_response,
    )
    executor = ToolExecutor(registry=registry, retailer=object())
    result = (
        await executor.execute_reads(
            [ToolCall(id="call-empty", name="probe_read")],
            access_token="token",
            store_id="store-1",
            allowed_names={"probe_read"},
        )
    )[0]

    assert result.success is False
    assert result.result_status == ToolResultStatus.INTERNAL_ERROR
    assert result.data["code"] == "INVALID_TOOL_RESPONSE"


@pytest.mark.asyncio
async def test_executor_marks_uncertain_write_failure_as_unknown_effect() -> None:
    async def raises_after_request(_arguments: dict[str, Any], _context: ToolContext):
        raise RuntimeError("response lost after request")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="probe_write", description="Write probe", risk=ToolRisk.WRITE
        ),
        raises_after_request,
    )
    executor = ToolExecutor(registry=registry, retailer=object())
    result = (
        await executor.execute_writes(
            [ToolCall(id="call-2", name="probe_write")],
            access_token="token",
            store_id="store-1",
            session_id="session-1",
            user_id="user-1",
            allowed_names={"probe_write"},
        )
    )[0]

    assert result.success is False
    assert result.result_status == ToolResultStatus.INTERNAL_ERROR
    assert result.effect_status == ToolEffectStatus.UNKNOWN
