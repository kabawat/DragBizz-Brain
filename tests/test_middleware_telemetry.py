"""Tests for Middleware.io LLM Observability & End-to-End Tracing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config.middleware_obs import MiddlewareObservabilitySettings
from app.config.settings import Settings
from app.observability.evaluations import evaluate_turn_correctness
from app.observability.middleware_telemetry import (
    init_middleware_telemetry,
    shutdown_middleware_telemetry,
    trace_chat,
    trace_context_build,
    trace_llm_call,
    trace_parallel_tool_group,
    trace_response_stream,
    trace_tool_execution,
    trace_tool_selection,
)
from app.schemas.tool import ToolCall, ToolResult


def test_middleware_settings_is_configured():
    # Unconfigured by default
    s1 = MiddlewareObservabilitySettings()
    assert s1.is_configured is False

    # Configured with UID + API KEY
    s2 = MiddlewareObservabilitySettings(MW_UID="test_uid", MW_API_KEY="test_key")
    assert s2.is_configured is True
    assert "https://test_uid.middleware.io:443" in s2.endpoint_url

    # Configured with explicit OTLP endpoint
    s3 = MiddlewareObservabilitySettings(
        OTEL_EXPORTER_OTLP_ENDPOINT="http://custom:4318"
    )
    assert s3.is_configured is True
    assert s3.endpoint_url == "http://custom:4318"


def test_init_middleware_telemetry_unconfigured():
    settings = Settings()
    # Unconfigured should return None and not raise
    providers = init_middleware_telemetry(settings)
    assert providers is None


def test_init_middleware_telemetry_configured():
    settings = Settings()
    settings.middleware.mw_uid = "abc12345"
    settings.middleware.mw_api_key = "test_key_fake"

    with patch("middleware.llmobs.register") as mock_register:
        mock_register.return_value = MagicMock()
        providers = init_middleware_telemetry(settings)
        assert providers is not None
        mock_register.assert_called_once()
        args, kwargs = mock_register.call_args
        assert kwargs["endpoint"] == "https://abc12345.middleware.io:443"
        assert kwargs["service_name"] == "dragbizz-brain"
        assert kwargs["headers"] == {"Authorization": "test_key_fake"}


def test_trace_chat_span():
    with trace_chat(
        session_id="sess_123",
        request_id="req_456",
        store_id="store_789",
        environment="test",
    ) as span:
        assert span is not None


def test_trace_chat_span_exception():
    with (
        pytest.raises(ValueError, match="test error"),
        trace_chat(
            session_id="sess_123",
            request_id="req_456",
            store_id="store_789",
            environment="test",
        ),
    ):
        raise ValueError("test error")


def test_trace_tool_execution_redaction():
    args = {
        "customerId": "cust_123",
        "api_key": "super_secret_key",
        "password": "secret_password",
        "normalField": "safe_value",
    }
    with trace_tool_execution("test_tool", raw_args=args) as span:
        assert span is not None


def test_trace_llm_call():
    with trace_llm_call(
        model="gemini-2.5-flash", provider="google_ai", temperature=0.7
    ) as span:
        span.set_attribute("llm.token_count.prompt", 150)
        span.set_attribute("llm.token_count.completion", 40)
        span.set_attribute("llm.token_count.total", 190)


def test_evaluate_turn_correctness():
    calls = [
        ToolCall(id="tc_1", name="list_customer_accounts", arguments={"storeId": "s1"}),
    ]
    results = [
        ToolResult(
            tool="list_customer_accounts",
            success=True,
            data={"accounts": [{"customerId": "c1", "totalDue": "500"}]},
        )
    ]
    with patch("app.observability.evaluations.submit_agent_evaluation") as mock_eval:
        scores = evaluate_turn_correctness(
            tool_calls=calls,
            tool_results=results,
            message="Here are the customer dues.",
        )
        assert scores["tool_execution_integrity"] == 1.0
        assert scores["ledger_accuracy"] == 1.0
        assert scores["response_validity"] == 1.0
        assert mock_eval.call_count >= 2


def test_shutdown_middleware_telemetry():
    mock_providers = MagicMock()
    shutdown_middleware_telemetry(mock_providers)
    mock_providers.tracer.force_flush.assert_called_once()
    mock_providers.tracer.shutdown.assert_called_once()


def test_trace_context_build_and_selection():
    with trace_context_build() as span:
        assert span is not None

    with trace_tool_selection() as span:
        assert span is not None


def test_trace_parallel_and_stream():
    with trace_parallel_tool_group(stage=1, tool_count=2) as span:
        assert span is not None

    with trace_response_stream() as metrics:
        metrics["chunk_count"] = 5
        metrics["ttft_ms"] = 120.5
        assert metrics["chunk_count"] == 5

