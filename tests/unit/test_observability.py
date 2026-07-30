"""Phase 7 — metrics registry and immutable tool-execution audit trail."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.observability import AuditTrail, MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition, ToolResult, ToolRisk

STORE_ID = "507f1f77bcf86cd799439011"


# ------------------------------------------------------------------- metrics


def test_metrics_snapshot_counts_and_success_rate() -> None:
    metrics = MetricsRegistry()
    metrics.record_chat(100.0)
    metrics.record_chat(200.0)
    metrics.record_cap_block()
    metrics.record_provider_call(50.0, error=False)
    metrics.record_provider_call(150.0, error=True)
    metrics.record_tool("today_sale", success=True)
    metrics.record_tool("today_sale", success=True)
    metrics.record_tool("create_customer", success=False)

    snapshot = metrics.snapshot()
    assert snapshot["chat"]["requests"] == 2
    assert snapshot["chat"]["capBlocked"] == 1
    assert snapshot["chat"]["latency"] == {"avgMs": 150.0, "maxMs": 200.0}
    assert snapshot["provider"] == {
        "calls": 2,
        "errors": 1,
        "latency": {"avgMs": 100.0, "maxMs": 150.0},
    }
    assert snapshot["tools"]["executions"] == 3
    assert snapshot["tools"]["failures"] == 1
    assert snapshot["tools"]["successRate"] == pytest.approx(0.6667)
    assert snapshot["tools"]["byTool"]["create_customer"]["failures"] == 1


class FailingProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "failing"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise RuntimeError("provider exploded")


def test_gateway_records_provider_errors() -> None:
    provider = FailingProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    metrics = MetricsRegistry()
    gateway = AiGateway(router, metrics=metrics)

    with pytest.raises(RuntimeError):
        asyncio.run(
            gateway.generate(
                GenerationRequest(
                    messages=[ChatMessage(role="user", content="hi")]
                )
            )
        )
    snapshot = metrics.snapshot()
    assert snapshot["provider"]["calls"] == 1
    assert snapshot["provider"]["errors"] == 1


# --------------------------------------------------------------- audit trail


def test_audit_trail_appends_json_lines(tmp_path: Path) -> None:
    trail = AuditTrail(str(tmp_path / "audit" / "trail.jsonl"))
    trail.append({"tool": "create_customer", "success": True})
    trail.append({"tool": "release_invoice", "success": False})
    trail.close()

    lines = (tmp_path / "audit" / "trail.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tool"] == "create_customer"
    assert first["ts"]

    # Reopening appends — existing entries are never rewritten.
    trail = AuditTrail(str(tmp_path / "audit" / "trail.jsonl"))
    trail.append({"tool": "today_sale", "success": True})
    trail.close()
    lines = (tmp_path / "audit" / "trail.jsonl").read_text().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["tool"] == "create_customer"


def test_executor_writes_read_and_write_executions_to_trail(
    tmp_path: Path,
) -> None:
    from app.executors.tool_executor import ToolExecutor
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="today_sale",
            description="d",
            parameters={"type": "object", "properties": {}},
            risk=ToolRisk.READ,
        ),
        lambda args, ctx: _result("today_sale", True),
    )
    registry.register(
        ToolDefinition(
            name="create_customer",
            description="d",
            parameters={"type": "object", "properties": {}},
            risk=ToolRisk.WRITE,
        ),
        lambda args, ctx: _result("create_customer", True),
    )
    trail = AuditTrail(str(tmp_path / "trail.jsonl"))
    metrics = MetricsRegistry()
    executor = ToolExecutor(
        registry=registry,
        retailer=MagicMock(),
        audit_trail=trail,
        metrics=metrics,
    )

    async def run() -> None:
        await executor.execute_reads(
            [ToolCall(id="1", name="today_sale", arguments={})],
            access_token="t",
            store_id=STORE_ID,
            session_id="s1",
            user_id="u1",
        )
        await executor.execute_writes(
            [ToolCall(id="2", name="create_customer", arguments={})],
            access_token="t",
            store_id=STORE_ID,
            session_id="s1",
            user_id="u1",
        )

    asyncio.run(run())
    trail.close()

    events = [
        json.loads(line)
        for line in (tmp_path / "trail.jsonl").read_text().splitlines()
    ]
    assert [event["tool"] for event in events] == [
        "today_sale",
        "create_customer",
    ]
    assert all(event["storeId"] == STORE_ID for event in events)
    assert all(event["userId"] == "u1" for event in events)
    assert events[1]["idempotencyKeyPrefix"]
    assert metrics.snapshot()["tools"]["executions"] == 2


async def _async_result(tool: str, success: bool) -> ToolResult:
    return ToolResult(tool=tool, success=success, data={})


def _result(tool: str, success: bool):
    return _async_result(tool, success)
