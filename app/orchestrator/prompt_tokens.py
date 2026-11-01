"""Heuristic per-component prompt token estimates for chat metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.rag.chunker import estimate_tokens
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolDefinition


@dataclass(frozen=True)
class PromptTokenBreakdown:
    system: int
    tools: int
    rag: int
    history: int
    user: int


def estimate_prompt_token_breakdown(
    *,
    system_content: str,
    documentation: str,
    tools: list[ToolDefinition] | tuple[ToolDefinition, ...],
    history_messages: list[ChatMessage],
    user_text: str,
) -> PromptTokenBreakdown:
    """Estimate input components (not provider billing tokens).

    ``system_content`` is the full system message (may include Documentation).
    RAG tokens are counted separately and subtracted from system.
    """
    rag = estimate_tokens(documentation) if documentation else 0
    docs_header = estimate_tokens("\nDocumentation:\n") if documentation else 0
    system_total = estimate_tokens(system_content)
    system = max(0, system_total - rag - docs_header)
    tools_tokens = estimate_tool_schema_tokens(tools)
    history = sum(estimate_tokens(message.content) for message in history_messages)
    user = estimate_tokens(user_text)
    return PromptTokenBreakdown(
        system=system,
        tools=tools_tokens,
        rag=rag,
        history=history,
        user=user,
    )


def estimate_tool_schema_tokens(
    tools: list[ToolDefinition] | tuple[ToolDefinition, ...],
) -> int:
    if not tools:
        return 0
    payload = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
    return estimate_tokens(json.dumps(payload, ensure_ascii=False))
