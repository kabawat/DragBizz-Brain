"""Phase 5: correlation, redaction, metrics, pricing, audit, taxonomy."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import tempfile
from pathlib import Path

import pytest

from app.confirmations import InMemoryConfirmationStore
from app.core.logging import JsonFormatter
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerHttpError, RetailerResponse
from app.observability.audit_trail import AUDIT_ALLOWLIST, AuditTrail, AuditTrailError
from app.observability.confirmation_audit import audit_confirmation
from app.observability.context import (
    correlation_fields,
    reset_auth_context,
    reset_request_id,
    set_auth_context,
    set_request_id,
)
from app.observability.events import CHAT_REQUEST, EVENT_NAMES, emit_event
from app.observability.failures import categorize_error_code
from app.observability.metrics import MetricsRegistry
from app.observability.pricing import ModelRate, PricingConfig
from app.observability.redaction import redact_mapping
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import stage_from_sensitive_calls
from app.schemas.chat import ConfirmRequest
from app.schemas.tool import ToolCall
from app.sessions import InMemorySessionStore
from app.tools.definitions import SENSITIVE_TOOL_DEFINITIONS
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE = "a" * 24
CUSTOMER = "b" * 24
SESSION = "sess-obs"


def _guard(message: str, **_kwargs: object) -> str:
    return message


def test_request_id_always_in_correlation() -> None:
    token = set_request_id("req-123")
    try:
        fields = correlation_fields()
        assert fields["request_id"] == "req-123"
        assert "user_id" not in fields
    finally:
        reset_request_id(token)


def test_auth_context_from_setters_only() -> None:
    rid = set_request_id("req-auth")
    auth = set_auth_context(
        user_id="user-1", store_id=STORE, session_id=SESSION
    )
    try:
        fields = correlation_fields()
        assert fields == {
            "request_id": "req-auth",
            "user_id": "user-1",
            "store_id": STORE,
            "session_id": SESSION,
        }
    finally:
        reset_auth_context(auth)
        reset_request_id(rid)
    assert "user_id" not in correlation_fields()


def test_reset_auth_context_across_contexts() -> None:
    """StreamingResponse iterates in another Context; reset must not raise."""
    holder: dict[str, object] = {}

    def _bind() -> None:
        holder["tokens"] = set_auth_context(
            user_id="user-x", store_id=STORE, session_id=SESSION
        )

    contextvars.copy_context().run(_bind)
    reset_auth_context(holder["tokens"])  # type: ignore[arg-type]
    assert "user_id" not in correlation_fields()


def test_json_formatter_reads_contextvars() -> None:
    token = set_request_id("req-fmt")
    try:
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))
        assert payload["request_id"] == "req-fmt"
    finally:
        reset_request_id(token)


def test_json_formatter_keeps_event_fields() -> None:
    record = logging.LogRecord(
        name="app.observability.events",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="rag.retrieve",
        args=(),
        exc_info=None,
    )
    record.event = "rag.retrieve"
    record.failed = True
    record.error = "AI_PROVIDER_ERROR"
    record.reason = "Embedding request failed"
    record.latency_ms = 12.5
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "rag.retrieve"
    assert payload["failed"] is True
    assert payload["error"] == "AI_PROVIDER_ERROR"
    assert payload["reason"] == "Embedding request failed"
    assert payload["latency_ms"] == 12.5


def test_redaction_sensitive_keys() -> None:
    redacted = redact_mapping(
        {
            "tool": "ok",
            "authorization": "Bearer secret",
            "nested": {"upiId": "user@upi", "amount": 10},
        }
    )
    assert redacted["tool"] == "ok"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["nested"]["upiId"] == "[REDACTED]"
    assert redacted["nested"]["amount"] == 10


def test_event_catalog() -> None:
    assert CHAT_REQUEST in EVENT_NAMES
    with pytest.raises(ValueError):
        emit_event("not.a.real.event")


def test_metrics_percentiles_and_no_high_cardinality() -> None:
    metrics = MetricsRegistry()
    for latency in (10, 100, 200, 500, 1000, 2000, 5000):
        metrics.record_chat(float(latency))
    snap = metrics.snapshot()
    assert snap["scope"] == "instance"
    assert "p50Ms" in snap["chat"]["latency"]
    assert "p95Ms" in snap["chat"]["latency"]
    assert "p99Ms" in snap["chat"]["latency"]
    dumped = json.dumps(snap)
    assert "userId" not in dumped
    assert "sessionId" not in dumped
    # storeId must not appear as a metric label key
    assert '"storeId"' not in dumped


def test_metrics_confirm_outcomes_and_limits() -> None:
    metrics = MetricsRegistry()
    metrics.record_confirm(status="SUCCEEDED")
    metrics.record_confirm(status="UNKNOWN")
    metrics.record_rate_limited()
    metrics.record_concurrency_limited()
    metrics.record_budget_exceeded()
    metrics.record_breaker_open()
    metrics.record_provider_call(12.0, error=True, retry=True)
    metrics.record_provider_call(8.0, error=False, fallback=True)
    metrics.record_rag(5.0, failed=True)
    metrics.record_failure_category("rate_limit")
    snap = metrics.snapshot()
    assert snap["confirm"]["outcomes"]["SUCCEEDED"] == 1
    assert snap["confirm"]["outcomes"]["UNKNOWN"] == 1
    assert snap["limits"]["rateLimited"] == 1
    assert snap["limits"]["concurrencyLimited"] == 1
    assert snap["limits"]["budgetExceeded"] == 1
    assert snap["breaker"]["opens"] == 1
    assert snap["provider"]["retries"] == 1
    assert snap["provider"]["fallbacks"] == 1
    assert snap["rag"]["failures"] == 1
    assert snap["failures"]["byCategory"]["rate_limit"] == 1


def test_usage_and_cost_sources() -> None:
    pricing = PricingConfig(
        pricing_version="v9",
        rates={
            ("openai_compatible", "gpt-4o-mini"): ModelRate(
                input_usd_per_million=0.15,
                output_usd_per_million=0.60,
                authoritative=True,
            )
        },
        default_rate=None,
    )
    calculated = pricing.compute_chat_cost(
        provider="openai_compatible",
        model="gpt-4o-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        usage_source="actual",
    )
    assert calculated.usage_source == "actual"
    assert calculated.cost_source == "calculated"
    assert calculated.pricing_version == "v9"
    assert calculated.cost_usd == pytest.approx(0.75)

    estimated = pricing.compute_chat_cost(
        provider="openai_compatible",
        model="gpt-4o-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        usage_source="estimated",
    )
    assert estimated.usage_source == "estimated"
    assert estimated.cost_source == "estimated"

    missing = pricing.compute_chat_cost(
        provider="unknown",
        model="x",
        input_tokens=100,
        output_tokens=100,
        usage_source="actual",
    )
    assert missing.cost_source == "estimated"
    assert missing.cost_usd is None


def test_failure_taxonomy() -> None:
    assert categorize_error_code("AI_RATE_LIMITED") == "rate_limit"
    assert categorize_error_code("CONFIRMATION_EXPIRED") == "confirmation"
    assert categorize_error_code("RETAILER_TIMEOUT") == "retailer"
    assert categorize_error_code("NOPE") == "internal"


def test_audit_trail_rejects_unknown_keys() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        trail = AuditTrail(str(path))
        try:
            with pytest.raises(AuditTrailError):
                trail.append(
                    {
                        "event": "tool.execution",
                        "tool": "search_products",
                        "success": True,
                        "payload": {"secret": "no"},
                    }
                )
            assert path.read_text() == ""
            trail.append(
                {
                    "event": "tool.execution",
                    "tool": "search_products",
                    "success": True,
                }
            )
            lines = path.read_text().strip().splitlines()
            assert len(lines) == 1
            assert "payload" not in lines[0]
        finally:
            trail.close()


def test_audit_allowlist_covers_confirmation_fields() -> None:
    required = {
        "event",
        "confirmationId",
        "type",
        "status",
        "previousStatus",
        "userId",
        "storeId",
        "sessionId",
        "requestId",
        "idempotencyKeyPrefix",
        "tool",
    }
    assert required <= AUDIT_ALLOWLIST


def test_confirmation_audit_canonical_statuses() -> None:
    asyncio.run(_confirmation_audit_flow())


async def _confirmation_audit_flow() -> None:
    class OkRetailer:
        async def create_ledger_transaction(self, **kwargs):
            return RetailerResponse(status_code=200, body={"data": {"id": "tx1"}})

    registry = ToolRegistry()
    for definition in SENSITIVE_TOOL_DEFINITIONS:
        registry.register(definition, SENSITIVE_TOOL_HANDLERS[definition.name])
    confirmations = InMemoryConfirmationStore()
    metrics = MetricsRegistry()
    with tempfile.TemporaryDirectory() as tmp:
        trail = AuditTrail(str(Path(tmp) / "a.jsonl"))
        try:
            staged = await stage_from_sensitive_calls(
                confirmations,
                user_id="u1",
                store_id=STORE,
                session_id=SESSION,
                sensitive_calls=[
                    ToolCall(
                        id="c1",
                        name="ledger_credit",
                        arguments={
                            "storeId": STORE,
                            "customerId": CUSTOMER,
                            "amount": 10,
                        },
                    )
                ],
                audit_trail=trail,
                metrics=metrics,
            )
            assert staged is not None
            response = await handle_confirm(
                ConfirmRequest(
                    sessionId=SESSION,
                    storeId=STORE,
                    confirmationId=staged.confirmation_id,
                    draftId=CUSTOMER,
                    action="approve",
                ),
                user_id="u1",
                request_id="r1",
                store_id=STORE,
                access_token="tok",
                confirmations=confirmations,
                sessions=InMemorySessionStore(),
                executor=ToolExecutor(registry=registry, retailer=OkRetailer()),
                guard_output=_guard,
                audit_trail=trail,
                metrics=metrics,
            )
            assert "recorded" in response.message.lower()
            lines = [
                json.loads(line)
                for line in Path(tmp).joinpath("a.jsonl").read_text().splitlines()
            ]
            statuses = [line["status"] for line in lines]
            assert "PENDING" in statuses
            assert "EXECUTING" in statuses
            assert "SUCCEEDED" in statuses
            assert metrics.snapshot()["confirm"]["outcomes"]["SUCCEEDED"] == 1
        finally:
            trail.close()


def test_confirmation_unknown_status_string() -> None:
    asyncio.run(_unknown_status())


async def _unknown_status() -> None:
    class TimeoutRetailer:
        async def create_ledger_transaction(self, **kwargs):
            raise RetailerHttpError(
                status_code=504,
                code="RETAILER_TIMEOUT",
                message="Retailer request timed out",
            )

    registry = ToolRegistry()
    for definition in SENSITIVE_TOOL_DEFINITIONS:
        registry.register(definition, SENSITIVE_TOOL_HANDLERS[definition.name])
    confirmations = InMemoryConfirmationStore()
    metrics = MetricsRegistry()
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="ledger_credit",
                arguments={
                    "storeId": STORE,
                    "customerId": CUSTOMER,
                    "amount": 10,
                },
            )
        ],
    )
    assert staged is not None
    await handle_confirm(
        ConfirmRequest(
            sessionId=SESSION,
            storeId=STORE,
            confirmationId=staged.confirmation_id,
            draftId=CUSTOMER,
            action="approve",
        ),
        user_id="u1",
        request_id="r1",
        store_id=STORE,
        access_token="tok",
        confirmations=confirmations,
        sessions=InMemorySessionStore(),
        executor=ToolExecutor(registry=registry, retailer=TimeoutRetailer()),
        guard_output=_guard,
        metrics=metrics,
    )
    assert metrics.snapshot()["confirm"]["outcomes"]["UNKNOWN"] == 1


def test_audit_confirmation_helper_rejects_via_trail() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        trail = AuditTrail(str(Path(tmp) / "a.jsonl"))
        try:
            # Helper only writes allowlisted fields.
            audit_confirmation(
                audit_trail=trail,
                metrics=None,
                confirmation_id="c1",
                type="ledger_credit",
                status="PENDING",
                previous_status=None,
                user_id="u1",
                store_id=STORE,
                session_id=SESSION,
                tool="ledger_credit",
            )
            line = json.loads(Path(tmp).joinpath("a.jsonl").read_text().strip())
            assert line["status"] == "PENDING"
            assert set(line) - {"ts"} <= AUDIT_ALLOWLIST
        finally:
            trail.close()
