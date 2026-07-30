"""Bounded multi-round tool validate → execute → continue loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.config import Settings
from app.confirmations import InMemoryConfirmationStore, PendingConfirmationRecord
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.confirmation import stage_from_sensitive_calls
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.schemas.chat import ChatMessage, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition, ToolResult, ToolRisk
from app.tools.registry import ToolRegistry


@dataclass
class ToolLoopOutcome:
    generation: GenerationResponse
    generations: list[GenerationResponse] = field(default_factory=list)
    all_calls: list[ToolCall] = field(default_factory=list)
    all_results: list[ToolResult] = field(default_factory=list)
    all_write_results: list[ToolResult] = field(default_factory=list)
    staged_sensitive: PendingConfirmationRecord | None = None


def call_signature(call: ToolCall) -> tuple[str, str]:
    return (
        call.name,
        json.dumps(call.arguments, sort_keys=True, ensure_ascii=False),
    )


def partition_tool_calls(
    tool_calls: list[ToolCall],
    *,
    registry: ToolRegistry,
) -> tuple[list[ToolCall], list[ToolCall], list[ToolCall]]:
    reads: list[ToolCall] = []
    writes: list[ToolCall] = []
    sensitive: list[ToolCall] = []
    for call in tool_calls:
        risk = registry.get_definition(call.name).risk
        if risk == ToolRisk.READ:
            reads.append(call)
        elif risk == ToolRisk.WRITE:
            writes.append(call)
        elif risk == ToolRisk.SENSITIVE:
            sensitive.append(call)
        else:
            raise AppError(
                code="TOOL_NOT_EXECUTABLE",
                message=f"Tool '{call.name}' has unsupported risk",
                status_code=400,
            )
    return reads, writes, sensitive


async def run_tool_loop(
    *,
    gateway: AiGateway,
    validator: ToolCallValidator,
    registry: ToolRegistry,
    executor: ToolExecutor,
    confirmations: InMemoryConfirmationStore,
    settings: Settings,
    generation: GenerationResponse,
    messages: list[ChatMessage],
    tools: list[ToolDefinition],
    language: str,
    store_id: str,
    access_token: str,
    session_id: str,
    user_id: str,
) -> ToolLoopOutcome:
    """Bounded multi-round tool loop: after each round's results the LLM
    may call the next tools (search -> draft) so multi-step requests
    finish in ONE user turn instead of asking permission per step."""
    generations = [generation]
    conversation = list(messages)
    all_calls: list[ToolCall] = []
    all_results: list[ToolResult] = []
    all_write_results: list[ToolResult] = []
    staged_sensitive: PendingConfirmationRecord | None = None
    successful_drafts = 0
    executed_signatures: set[tuple[str, str]] = set()
    max_rounds = settings.chat_max_tool_rounds

    def _describe_errors(tool_calls: list[ToolCall], sid: str) -> list[str]:
        return validator.describe_errors(tool_calls, store_id=sid)

    for round_index in range(max_rounds):
        try:
            tool_calls = validator.validate(
                generation.tool_calls, store_id=store_id
            )
        except AppError as exc:
            if exc.code not in {"TOOL_ARGS_INVALID", "TOOL_NOT_ALLOWED"}:
                raise
            generation = await gateway.repair_tool_calls(
                messages=conversation,
                tools=tools,
                previous=generation,
                store_id=store_id,
                detail=exc.message,
                temperature=settings.chat_temperature,
                max_tokens=settings.chat_max_tokens,
                describe_errors=_describe_errors,
            )
            generations.append(generation)
            tool_calls = validator.validate(
                generation.tool_calls, store_id=store_id
            )

        if not tool_calls:
            break

        # Guard: never re-execute a (tool, args) pair already run this
        # turn — a looping model must answer instead of burning rounds.
        tool_calls = [
            call
            for call in tool_calls
            if call_signature(call) not in executed_signatures
        ]
        if not tool_calls:
            generation = await gateway.continue_or_synthesize(
                conversation,
                tools,
                language=language,
                allow_tools=False,
                temperature=settings.chat_temperature,
                max_tokens=settings.chat_synthesis_max_tokens,
            )
            generations.append(generation)
            break
        executed_signatures.update(call_signature(call) for call in tool_calls)

        read_calls, write_calls, sensitive_calls = partition_tool_calls(
            tool_calls, registry=registry
        )
        read_results = await executor.execute_reads(
            read_calls,
            access_token=access_token,
            store_id=store_id,
            session_id=session_id,
            user_id=user_id,
        )
        write_results = await executor.execute_writes(
            write_calls,
            access_token=access_token,
            store_id=store_id,
            session_id=session_id,
            user_id=user_id,
            prior_successful_drafts=successful_drafts,
        )
        successful_drafts += sum(
            1
            for result in write_results
            if result.tool == "create_invoice_draft" and result.success
        )
        # Sensitive calls are staged (not executed) — placeholder results.
        staged_sensitive = stage_from_sensitive_calls(
            confirmations,
            user_id=user_id,
            store_id=store_id,
            session_id=session_id,
            sensitive_calls=sensitive_calls,
        )
        sensitive_placeholders = [
            ToolResult(
                tool=call.name,
                success=True,
                data={
                    "status": "pending_confirmation",
                    "confirmationId": (
                        staged_sensitive.confirmation_id
                        if staged_sensitive is not None
                        else None
                    ),
                    "draftId": (
                        staged_sensitive.draft_id
                        if staged_sensitive is not None
                        else call.arguments.get("invoiceId")
                    ),
                },
            )
            for call in sensitive_calls
        ]
        # Preserve original tool_calls order for pairing.
        results_by_id = {
            call.id: result
            for call, result in zip(
                [*read_calls, *write_calls, *sensitive_calls],
                [*read_results, *write_results, *sensitive_placeholders],
                strict=True,
            )
        }
        round_results = [results_by_id[call.id] for call in tool_calls]

        all_calls.extend(tool_calls)
        all_results.extend(round_results)
        all_write_results.extend(write_results)

        conversation.append(
            ChatMessage(role="assistant", content="", tool_calls=tool_calls)
        )
        for call, result in zip(tool_calls, round_results, strict=True):
            conversation.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    content=json.dumps(
                        {
                            "tool": result.tool,
                            "success": result.success,
                            "data": result.data,
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        # Once a confirmation is staged, or on the last round, force a
        # final grounded answer instead of allowing more tool calls.
        allow_more_tools = (
            staged_sensitive is None and round_index < max_rounds - 1
        )
        generation = await gateway.continue_or_synthesize(
            conversation,
            tools,
            language=language,
            allow_tools=allow_more_tools,
            temperature=settings.chat_temperature,
            max_tokens=settings.chat_synthesis_max_tokens,
        )
        generations.append(generation)
        if not allow_more_tools:
            break

    return ToolLoopOutcome(
        generation=generation,
        generations=generations,
        all_calls=all_calls,
        all_results=all_results,
        all_write_results=all_write_results,
        staged_sensitive=staged_sensitive,
    )
