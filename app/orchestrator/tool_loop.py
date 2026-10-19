"""Bounded multi-round tool validate → execute → continue loop."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.confirmations import ConfirmationStore, PendingConfirmationRecord
from app.core.exceptions import AppError
from app.executors.dependencies import StageKind, plan_execution
from app.executors.tool_executor import ToolExecutor
from app.limits.request_budget import BudgetExceeded, RequestBudget
from app.observability.audit_trail import AuditTrail
from app.observability.metrics import MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.cancel import CancelScope
from app.orchestrator.confirmation import stage_from_sensitive_calls
from app.orchestrator.context_optimize import (
    compact_conversation_for_next_round,
    compact_result_for_model,
    tools_for_continue,
)
from app.orchestrator.ledger_auto import (
    customer_label_for_id,
    ledger_pending_message,
    maybe_auto_ledger_call,
)
from app.orchestrator.prompt_tokens import estimate_tool_schema_tokens
from app.orchestrator.token_usage import RequestTokenUsage
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_selector import user_requested_sensitive_action
from app.rag.chunker import estimate_tokens
from app.schemas.chat import ChatMessage, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition, ToolResult, ToolRisk
from app.tools.projection import project_tool_result
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

StreamEmitFn = Callable[[str, dict[str, Any]], Awaitable[None] | None]


@dataclass
class ToolLoopOutcome:
    generation: GenerationResponse
    generations: list[GenerationResponse] = field(default_factory=list)
    all_calls: list[ToolCall] = field(default_factory=list)
    all_results: list[ToolResult] = field(default_factory=list)
    all_write_results: list[ToolResult] = field(default_factory=list)
    staged_sensitive: PendingConfirmationRecord | None = None
    compacted_tokens: int = 0
    removed_schema_tokens: int = 0
    removed_result_tokens: int = 0


def _latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content
    return ""


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


def _tool_summary(result: ToolResult) -> dict[str, Any]:
    code = None
    status = None
    if isinstance(result.data, dict):
        raw_code = result.data.get("code")
        raw_status = result.data.get("status")
        if isinstance(raw_code, str):
            code = raw_code
        if isinstance(raw_status, str):
            status = raw_status
    summary: dict[str, Any] = {"success": result.success}
    if code is not None:
        summary["code"] = code
    if status is not None:
        summary["status"] = status
    return summary


def _sensitive_placeholder(
    call: ToolCall, staged: PendingConfirmationRecord | None
) -> ToolResult:
    staged_for_call = staged is not None and staged.tool_name == call.name
    draft_id = (
        staged.draft_id
        if staged_for_call and staged is not None
        else call.arguments.get("invoiceId") or call.arguments.get("customerId")
    )
    confirmation_id = None
    if staged_for_call and staged is not None:
        confirmation_id = staged.confirmation_id
    data: dict[str, Any] = {
        "status": "pending_confirmation",
        "confirmationId": confirmation_id,
        "draftId": draft_id,
    }
    # Ground output-guard currency checks on the staged amount.
    amount = call.arguments.get("amount")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        data["amount"] = amount
    customer_id = call.arguments.get("customerId")
    if isinstance(customer_id, str) and customer_id.strip():
        data["customerId"] = customer_id.strip()
    if staged_for_call and staged is not None and staged.summary:
        data["summary"] = dict(staged.summary)
    return ToolResult(
        tool=call.name,
        success=True,
        data=data,
    )


async def _emit(
    emit: StreamEmitFn | None, event: str, payload: dict[str, Any]
) -> None:
    if emit is None:
        return
    result = emit(event, payload)
    if result is not None:
        await result


async def run_tool_loop(
    *,
    gateway: AiGateway,
    validator: ToolCallValidator,
    registry: ToolRegistry,
    executor: ToolExecutor,
    confirmations: ConfirmationStore,
    settings: Settings,
    generation: GenerationResponse,
    messages: list[ChatMessage],
    tools: list[ToolDefinition],
    language: str,
    store_id: str,
    access_token: str,
    session_id: str,
    user_id: str,
    agency_id: str | None = None,
    tenant_id: str | None = None,
    budget: RequestBudget | None = None,
    audit_trail: AuditTrail | None = None,
    metrics: MetricsRegistry | None = None,
    cancel: CancelScope | None = None,
    emit: StreamEmitFn | None = None,
    token_usage: RequestTokenUsage | None = None,
) -> ToolLoopOutcome:
    """Bounded multi-round tool loop: after each round's results the LLM
    may call the next tools (search -> draft) so multi-step requests
    finish in ONE user turn instead of asking permission per step."""
    generations = [generation]
    conversation = list(messages)
    question = _latest_user_text(messages)
    all_calls: list[ToolCall] = []
    all_results: list[ToolResult] = []
    all_write_results: list[ToolResult] = []
    staged_sensitive: PendingConfirmationRecord | None = None
    successful_drafts = 0
    executed_signatures: set[tuple[str, str]] = set()
    max_rounds = settings.chat.max_tool_rounds
    allowed_names = frozenset(tool.name for tool in tools)
    compacted_tokens = 0
    removed_schema_tokens = 0
    removed_result_tokens = 0

    def _describe_errors(tool_calls: list[ToolCall], sid: str) -> list[str]:
        return validator.describe_errors(
            tool_calls,
            store_id=sid,
            allowed_names=allowed_names,
            agency_id=agency_id,
            tenant_id=tenant_id,
        )

    for round_index in range(max_rounds):
        try:
            tool_calls = validator.validate(
                generation.tool_calls,
                store_id=store_id,
                allowed_names=allowed_names,
                agency_id=agency_id,
                tenant_id=tenant_id,
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
                temperature=settings.chat.temperature,
                max_tokens=settings.chat.max_tokens,
                describe_errors=_describe_errors,
                budget=budget,
                token_usage=token_usage,
                round=round_index,
            )
            generations.append(generation)
            tool_calls = validator.validate(
                generation.tool_calls,
                store_id=store_id,
                allowed_names=allowed_names,
                agency_id=agency_id,
                tenant_id=tenant_id,
            )

        if not tool_calls:
            if round_index == 0 and emit is not None and generation.content:
                await _emit(emit, "assistant.delta", {"text": generation.content})
            break

        # Guard: never re-execute a (tool, args) pair already run this
        # turn — a looping model must answer instead of burning rounds.
        tool_calls = [
            call
            for call in tool_calls
            if call_signature(call) not in executed_signatures
        ]
        if not tool_calls:
            if emit is not None:
                collected: list[str] = []
                async for chunk in gateway.continue_or_synthesize_stream(
                    conversation,
                    language=language,
                    temperature=settings.chat.temperature,
                    max_tokens=settings.chat.synthesis_max_tokens,
                    budget=budget,
                    token_usage=token_usage,
                    round=round_index,
                ):
                    collected.append(chunk)
                    await _emit(emit, "assistant.delta", {"text": chunk})
                generation = GenerationResponse(
                    provider=generations[0].provider if generations else "stream",
                    model=generations[0].model if generations else "",
                    content="".join(collected),
                    tool_calls=[],
                )
            else:
                generation = await gateway.continue_or_synthesize(
                    conversation,
                    tools,
                    language=language,
                    allow_tools=False,
                    temperature=settings.chat.temperature,
                    max_tokens=settings.chat.synthesis_max_tokens,
                    budget=budget,
                    token_usage=token_usage,
                    round=round_index,
                )
            generations.append(generation)
            break
        executed_signatures.update(call_signature(call) for call in tool_calls)

        if cancel is not None:
            cancel.raise_if_cancelled()
        if budget is not None:
            try:
                budget.begin_tool_batch(len(tool_calls))
            except BudgetExceeded:
                generation = await gateway.continue_or_synthesize(
                    conversation,
                    tools,
                    language=language,
                    allow_tools=False,
                    temperature=settings.chat.temperature,
                    max_tokens=settings.chat.synthesis_max_tokens,
                    budget=budget,
                    token_usage=token_usage,
                    round=round_index,
                )
                generations.append(generation)
                break

        _, write_calls, sensitive_calls = partition_tool_calls(
            tool_calls, registry=registry
        )
        stages = plan_execution(tool_calls, registry=registry)
        results_by_id_raw: dict[str, ToolResult] = {}

        for stage in stages:
            if cancel is not None:
                cancel.raise_if_cancelled()
            if budget is not None:
                budget.check_deadline()

            if stage.kind == StageKind.PARALLEL_READ:
                for call in stage.calls:
                    await _emit(
                        emit,
                        "tool.started",
                        {"tool": call.name, "toolCallId": call.id},
                    )
                stage_results = await executor.execute_reads(
                    list(stage.calls),
                    access_token=access_token,
                    store_id=store_id,
                    allowed_names=allowed_names,
                    session_id=session_id,
                    user_id=user_id,
                    question=question,
                    parallel=True,
                )
                for call, result in zip(stage.calls, stage_results, strict=True):
                    projected = project_tool_result(result)
                    results_by_id_raw[call.id] = projected
                    await _emit(
                        emit,
                        "tool.completed",
                        {
                            "tool": call.name,
                            "toolCallId": call.id,
                            "success": projected.success,
                            "summary": _tool_summary(projected),
                        },
                    )
            elif stage.kind == StageKind.SEQUENTIAL_READ:
                for call in stage.calls:
                    await _emit(
                        emit,
                        "tool.started",
                        {"tool": call.name, "toolCallId": call.id},
                    )
                    one = await executor.execute_reads(
                        [call],
                        access_token=access_token,
                        store_id=store_id,
                        allowed_names=allowed_names,
                        session_id=session_id,
                        user_id=user_id,
                        question=question,
                        parallel=False,
                    )
                    projected = project_tool_result(one[0])
                    results_by_id_raw[call.id] = projected
                    await _emit(
                        emit,
                        "tool.completed",
                        {
                            "tool": call.name,
                            "toolCallId": call.id,
                            "success": projected.success,
                            "summary": _tool_summary(projected),
                        },
                    )
            elif stage.kind == StageKind.SEQUENTIAL_WRITE:
                call = stage.calls[0]
                await _emit(
                    emit,
                    "tool.started",
                    {"tool": call.name, "toolCallId": call.id},
                )
                one = await executor.execute_writes(
                    [call],
                    access_token=access_token,
                    store_id=store_id,
                    session_id=session_id,
                    user_id=user_id,
                    allowed_names=allowed_names,
                    prior_successful_drafts=successful_drafts,
                )
                projected = project_tool_result(one[0])
                results_by_id_raw[call.id] = projected
                if call.name == "create_invoice_draft" and projected.success:
                    successful_drafts += 1
                await _emit(
                    emit,
                    "tool.completed",
                    {
                        "tool": call.name,
                        "toolCallId": call.id,
                        "success": projected.success,
                        "summary": _tool_summary(projected),
                    },
                )
            elif stage.kind == StageKind.SEQUENTIAL_SENSITIVE:
                continue

        allowed_sensitive = [
            call
            for call in sensitive_calls
            if user_requested_sensitive_action(question, call.name)
        ]
        blocked_sensitive_ids = {
            call.id for call in sensitive_calls if call not in allowed_sensitive
        }
        if allowed_sensitive:
            if cancel is not None:
                cancel.raise_if_cancelled()
            staged_sensitive = await stage_from_sensitive_calls(
                confirmations,
                user_id=user_id,
                store_id=store_id,
                session_id=session_id,
                sensitive_calls=allowed_sensitive,
                audit_trail=audit_trail,
                metrics=metrics,
                retailer=executor._retailer,
                access_token=access_token,
                question=question,
            )
        for call in sensitive_calls:
            await _emit(
                emit,
                "tool.started",
                {"tool": call.name, "toolCallId": call.id},
            )
            if call.id not in blocked_sensitive_ids:
                projected = project_tool_result(
                    _sensitive_placeholder(call, staged_sensitive)
                )
            else:
                projected = project_tool_result(
                    ToolResult(
                        tool=call.name,
                        success=False,
                        data={
                            "code": "SENSITIVE_NOT_REQUESTED",
                            "message": (
                                "This action was not requested by the user"
                            ),
                        },
                    )
                )
            results_by_id_raw[call.id] = projected
            await _emit(
                emit,
                "tool.completed",
                {
                    "tool": call.name,
                    "toolCallId": call.id,
                    "success": projected.success,
                    "summary": _tool_summary(projected),
                },
            )

        results_by_id = results_by_id_raw
        # Full projection for client/history; compacted copy for model messages.
        round_results = [results_by_id[call.id] for call in tool_calls]
        model_results = [
            compact_result_for_model(result) for result in round_results
        ]
        for full, slim in zip(round_results, model_results, strict=True):
            before = estimate_tokens(json.dumps(full.data or {}, ensure_ascii=False))
            after = estimate_tokens(json.dumps(slim.data or {}, ensure_ascii=False))
            removed_result_tokens += max(0, before - after)

        projected_writes = [
            results_by_id[call.id]
            for call in write_calls
            if call.id in results_by_id
        ]

        all_calls.extend(tool_calls)
        all_results.extend(round_results)
        all_write_results.extend(projected_writes)

        conversation.append(
            ChatMessage(role="assistant", content="", tool_calls=tool_calls)
        )
        for call, result in zip(tool_calls, model_results, strict=True):
            conversation.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    content=json.dumps(
                        {
                            "tool": result.tool,
                            "success": result.success,
                            "data": result.data,
                            "untrusted": True,
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        if staged_sensitive is None:
            auto_ledger = maybe_auto_ledger_call(
                question=question,
                store_id=store_id,
                allowed_names=allowed_names,
                results=all_results,
                already_called={call.name for call in all_calls},
            )
            if auto_ledger is not None:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                staged_sensitive = await stage_from_sensitive_calls(
                    confirmations,
                    user_id=user_id,
                    store_id=store_id,
                    session_id=session_id,
                    sensitive_calls=[auto_ledger],
                    audit_trail=audit_trail,
                    metrics=metrics,
                    retailer=executor._retailer,
                    access_token=access_token,
                    question=question,
                )
                projected = project_tool_result(
                    _sensitive_placeholder(auto_ledger, staged_sensitive)
                )
                all_calls.append(auto_ledger)
                all_results.append(projected)
                amount = auto_ledger.arguments.get("amount")
                customer_id = str(auto_ledger.arguments.get("customerId") or "")
                generation = GenerationResponse(
                    provider=generation.provider,
                    model=generation.model,
                    content=ledger_pending_message(
                        tool_name=auto_ledger.name,
                        amount=amount if isinstance(amount, (int, float)) else 0,
                        customer_name=customer_label_for_id(
                            all_results, customer_id
                        ),
                        language=language,
                    ),
                )
                generations.append(generation)
                break

        draft_done = any(
            result.success
            and result.tool
            in {"create_invoice_draft", "update_invoice_draft"}
            for result in projected_writes
        )
        allow_more_tools = (
            staged_sensitive is None
            and round_index < max_rounds - 1
            and not draft_done
        )
        if budget is not None and not budget.can_continue():
            allow_more_tools = False

        if allow_more_tools:
            continue_tools = tools_for_continue(
                tools,
                registry=registry,
                results=all_results,
                staged_sensitive=staged_sensitive is not None,
            )
            removed_schema_tokens += max(
                0,
                estimate_tool_schema_tokens(tools)
                - estimate_tool_schema_tokens(continue_tools),
            )
        else:
            continue_tools = []

        conversation, removed = compact_conversation_for_next_round(conversation)
        compacted_tokens += removed

        if not allow_more_tools and emit is not None:
            collected: list[str] = []
            try:
                async for chunk in gateway.continue_or_synthesize_stream(
                    conversation,
                    language=language,
                    temperature=settings.chat.temperature,
                    max_tokens=settings.chat.synthesis_max_tokens,
                    budget=budget,
                    token_usage=token_usage,
                    round=round_index + 1,
                ):
                    collected.append(chunk)
                    await _emit(emit, "assistant.delta", {"text": chunk})
                generation = GenerationResponse(
                    provider=generations[0].provider if generations else "stream",
                    model=generations[0].model if generations else "",
                    content="".join(collected),
                    tool_calls=[],
                )
            except BudgetExceeded:
                raise
            except Exception:
                if collected:
                    raise
                logger.warning(
                    "Synthesis streaming failed; using non-stream fallback",
                    exc_info=True,
                )
                generation = await gateway.continue_or_synthesize(
                    conversation,
                    [],
                    language=language,
                    allow_tools=False,
                    temperature=settings.chat.temperature,
                    max_tokens=settings.chat.synthesis_max_tokens,
                    budget=budget,
                    token_usage=token_usage,
                    round=round_index + 1,
                )
        else:
            try:
                generation = await gateway.continue_or_synthesize(
                    conversation,
                    continue_tools,
                    language=language,
                    allow_tools=allow_more_tools,
                    temperature=settings.chat.temperature,
                    max_tokens=settings.chat.synthesis_max_tokens,
                    budget=budget,
                    token_usage=token_usage,
                    round=round_index + 1,
                )
            except BudgetExceeded:
                if allow_more_tools:
                    generation = await gateway.continue_or_synthesize(
                        conversation,
                        [],
                        language=language,
                        allow_tools=False,
                        temperature=settings.chat.temperature,
                        max_tokens=settings.chat.synthesis_max_tokens,
                        budget=budget,
                        token_usage=token_usage,
                        round=round_index + 1,
                    )
                else:
                    raise
        generations.append(generation)
        if not allow_more_tools:
            break

    if metrics is not None:
        metrics.record_compaction(
            compacted=compacted_tokens,
            removed_schemas=removed_schema_tokens,
            removed_results=removed_result_tokens,
        )

    return ToolLoopOutcome(
        generation=generation,
        generations=generations,
        all_calls=all_calls,
        all_results=all_results,
        all_write_results=all_write_results,
        staged_sensitive=staged_sensitive,
        compacted_tokens=compacted_tokens,
        removed_schema_tokens=removed_schema_tokens,
        removed_result_tokens=removed_result_tokens,
    )
