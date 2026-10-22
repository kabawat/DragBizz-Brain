"""Middleware.io LLM Observability & End-to-End Tracing for DragBizz Brain.

Provides production-safe, privacy-conscious manual and provider instrumentation
conforming to OpenInference and OpenTelemetry semantic conventions.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from openinference.semconv.trace import (
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode, Tracer

from app.config import Settings
from app.observability.redaction import redact_mapping

logger = logging.getLogger(__name__)

_TRACER_NAME = "dragbizz-brain"
_global_providers: Any = None


def get_tracer() -> Tracer:
    """Returns the OpenTelemetry tracer for DragBizz Brain."""
    return trace.get_tracer(_TRACER_NAME)


def init_middleware_telemetry(settings: Settings) -> Any:
    """Initialize Middleware LLM Observability once at application startup."""
    global _global_providers

    # If environment variables are set directly, populate settings
    endpoint = settings.middleware.endpoint_url
    api_key = settings.middleware.mw_api_key or os.getenv("MW_API_KEY")
    service_name = settings.middleware.service_name or "dragbizz-brain"
    project_name = settings.middleware.mw_project_name or "dragbizz-brain"
    env_name = settings.middleware.deployment_environment or settings.server.environment

    headers = {}
    if api_key:
        headers["Authorization"] = api_key

    is_configured = bool(
        settings.middleware.is_configured
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or (settings.middleware.mw_uid and api_key)
    )

    if not is_configured:
        logger.info(
            "Middleware.io observability unconfigured (MW_UID / MW_API_KEY not set). "
            "Running with safe OpenTelemetry fallback."
        )
        return None

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        if not hasattr(OTLPSpanExporter, "_headers"):
            OTLPSpanExporter._headers = property(
                lambda self: getattr(getattr(self, "_client", None), "headers", {})
            )
    except Exception:
        pass

    try:
        from middleware import llmobs

        # Register Middleware LLMObs with batch exporter
        providers = llmobs.register(
            endpoint=endpoint,
            headers=headers if headers else None,
            service_name=service_name,
            project_name=project_name,
            batch=True,
            auto_instrument=False,
            verbose=False,
        )
        _global_providers = providers
        logger.info(
            "Middleware LLM Observability initialized for %s (%s) at %s",
            service_name,
            env_name,
            endpoint,
        )
        return providers
    except Exception as exc:
        logger.warning(
            "Failed to initialize Middleware LLM Observability: %s. "
            "Telemetry will fail-open safely.",
            exc,
            exc_info=True,
        )
        return None


def shutdown_middleware_telemetry(providers: Any = None) -> None:
    """Cleanly flush and shut down telemetry providers."""
    target = providers or _global_providers
    if target is None:
        return

    try:
        if hasattr(target, "tracer") and target.tracer:
            target.tracer.force_flush(timeout_millis=3000)
            target.tracer.shutdown()
        logger.info("Middleware LLM Observability flushed and shut down successfully.")
    except Exception as exc:
        logger.warning("Error during Middleware telemetry shutdown: %s", exc)


@contextmanager
def trace_chat(
    *,
    session_id: str,
    request_id: str,
    store_id: str,
    environment: str = "production",
) -> Iterator[Span]:
    """Root span for an end-to-end chat turn."""
    tracer = get_tracer()
    with tracer.start_as_current_span("brain.chat") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.AGENT.value,
        )
        span.set_attribute("session.id", session_id)
        span.set_attribute("request.id", request_id)
        span.set_attribute("store.id", store_id)
        span.set_attribute("deployment.environment", environment)
        span.set_attribute("operation.type", "chat")
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


@contextmanager
def trace_intent(text_length: int) -> Iterator[Span]:
    """Child span for intent routing."""
    tracer = get_tracer()
    with tracer.start_as_current_span("brain.intent_resolution") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.DECISION.value,
        )
        span.set_attribute("input.length", text_length)
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


@contextmanager
def trace_context_build() -> Iterator[Span]:
    """Child span for context building."""
    tracer = get_tracer()
    with tracer.start_as_current_span("brain.context_build") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.CHAIN.value,
        )
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


@contextmanager
def trace_tool_selection() -> Iterator[Span]:
    """Child span for tool filtering and exposure."""
    tracer = get_tracer()
    with tracer.start_as_current_span("brain.tool_selection") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.CHAIN.value,
        )
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


@contextmanager
def trace_llm_call(
    *,
    model: str,
    provider: str,
    temperature: float | None = None,
) -> Iterator[Span]:
    """Child span for an individual LLM invocation."""
    tracer = get_tracer()
    with tracer.start_as_current_span("brain.llm_call") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.LLM.value,
        )
        span.set_attribute(SpanAttributes.LLM_MODEL_NAME, model)
        span.set_attribute("llm.provider", provider)
        if temperature is not None:
            span.set_attribute(
                SpanAttributes.LLM_INVOCATION_PARAMETERS,
                f'{{"temperature": {temperature}}}',
            )
        start_t = time.perf_counter()
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start_t) * 1000
            span.set_attribute("llm.duration_ms", duration_ms)


@contextmanager
def trace_tool_execution(
    tool_name: str, raw_args: dict[str, Any] | None = None
) -> Iterator[Span]:
    """Child span for tool execution with parameter redaction."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"brain.tool.{tool_name}") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.TOOL.value,
        )
        span.set_attribute(SpanAttributes.TOOL_NAME, tool_name)
        if raw_args:
            safe_args = redact_mapping(raw_args)
            safe_keys = list(safe_args.keys())
            span.set_attribute("tool.parameters.keys", ",".join(safe_keys))

        start_t = time.perf_counter()
        try:
            yield span
            span.set_status(StatusCode.OK)
            span.set_attribute("tool.status", "success")
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.set_attribute("tool.status", "error")
            span.record_exception(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start_t) * 1000
            span.set_attribute("tool.duration_ms", duration_ms)


@contextmanager
def trace_parallel_tool_group(stage: int, tool_count: int) -> Iterator[Span]:
    """Child span for parallel tool execution groups."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"brain.parallel_tool_group.{stage}") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.CHAIN.value,
        )
        span.set_attribute("stage.index", stage)
        span.set_attribute("stage.tool_count", tool_count)
        start_t = time.perf_counter()
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start_t) * 1000
            span.set_attribute("stage.duration_ms", duration_ms)


@contextmanager
def trace_response_stream() -> Iterator[dict[str, Any]]:
    """Child span for streaming response timing and TTFT."""
    tracer = get_tracer()
    metrics: dict[str, Any] = {
        "ttft_ms": None,
        "first_chunk_ts": None,
        "chunk_count": 0,
        "total_duration_ms": 0.0,
    }
    with tracer.start_as_current_span("brain.response_stream") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.CHAIN.value,
        )
        start_t = time.perf_counter()
        try:
            yield metrics
            span.set_status(StatusCode.OK)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            total_duration_ms = (time.perf_counter() - start_t) * 1000
            metrics["total_duration_ms"] = total_duration_ms
            span.set_attribute("streaming.total_duration_ms", total_duration_ms)
            span.set_attribute("streaming.chunk_count", metrics["chunk_count"])
            if metrics["ttft_ms"] is not None:
                span.set_attribute("streaming.ttft_ms", metrics["ttft_ms"])


def submit_agent_evaluation(
    *,
    name: str,
    value: float,
    comment: str = "",
) -> None:
    """Submit a deterministic evaluation score to Middleware."""
    try:
        from middleware import llmobs

        llmobs.submit_evaluation(
            name=name,
            value=value,
            comment=comment,
        )
    except Exception as exc:
        logger.debug("Evaluation submission skipped or failed: %s", exc)
