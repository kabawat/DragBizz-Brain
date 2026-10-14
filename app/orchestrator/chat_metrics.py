from __future__ import annotations

from app.observability.events import CHAT_REQUEST, emit_event
from app.observability.pricing import CostResult
from app.orchestrator.prompt_tokens import PromptTokenBreakdown
from app.orchestrator.token_usage import RequestTokenUsage
from app.rag.models import RetrievedChunk
from app.schemas.chat import GenerationResponse
from app.schemas.tool import ToolCall


def log_request_metrics(
    *,
    generations: list[GenerationResponse],
    retrieved: list[RetrievedChunk],
    tool_calls: list[ToolCall],
    history_turns: int,
    latency_ms: float,
    input_tokens: int | None,
    output_tokens: int | None,
    cost: CostResult,
    token_breakdown: PromptTokenBreakdown,
    rag_cache_hit: bool,
    outcome: str,
    token_usage: RequestTokenUsage | None = None,
    compacted_tokens: int = 0,
    removed_schema_tokens: int = 0,
    removed_result_tokens: int = 0,
) -> None:
    # Doc IDs/scores, tokens, latency, cost — never question or answer text.
    final = generations[-1]
    usage_agg = token_usage.aggregate() if token_usage is not None else {}
    total_tokens = (
        usage_agg.get("totalTokens")
        if usage_agg
        else (
            (input_tokens or 0) + (output_tokens or 0)
            if input_tokens is not None or output_tokens is not None
            else None
        )
    )
    metrics_payload = {
        "latency_ms": round(latency_ms, 1),
        "outcome": outcome,
        "provider": final.provider,
        "model": final.model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost.cost_usd,
        "model_calls": usage_agg.get("modelCalls", len(generations)),
        "tools_called": [call.name for call in tool_calls],
        "rag_docs": len(retrieved),
        "rag_cache_hit": rag_cache_hit,
        "prompt_rag_tokens": token_breakdown.rag,
        "history_turns": history_turns,
    }
    if compacted_tokens or removed_schema_tokens or removed_result_tokens:
        metrics_payload["compacted_tokens"] = compacted_tokens
        metrics_payload["removed_schema_tokens"] = removed_schema_tokens
        metrics_payload["removed_result_tokens"] = removed_result_tokens
    emit_event(CHAT_REQUEST, metrics=metrics_payload, outcome=outcome)
