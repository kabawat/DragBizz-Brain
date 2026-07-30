from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import Settings
from app.confirmations import InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.observability.metrics import MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.confirmation import (
    pending_to_schema,
    stage_from_draft_result,
    stage_from_sensitive_calls,
)
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.prompts.fallback import get_fallback_message
from app.prompts.refusal import get_refusal_message
from app.prompts.synthesis import (
    build_continuation_instruction,
    build_synthesis_instruction,
)
from app.prompts.system.chat import (
    build_chat_system_prompt,
    build_documentation_block,
)
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    GenerationRequest,
    GenerationResponse,
    PendingConfirmation,
)
from app.schemas.tool import ToolCall, ToolDefinition, ToolResult, ToolRisk
from app.sessions import (
    InMemorySessionStore,
    SessionStore,
    SessionTurn,
    turns_to_messages,
)
from app.tools.registry import ToolRegistry
from app.usage import InMemoryUsageStore, UsageStore

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        *,
        gateway: AiGateway,
        tool_registry: ToolRegistry,
        settings: Settings,
        tool_executor: ToolExecutor,
        validator: ToolCallValidator | None = None,
        retriever: Retriever | None = None,
        input_guard: InputGuard | None = None,
        output_guard: OutputGuard | None = None,
        session_store: SessionStore | None = None,
        confirmation_store: InMemoryConfirmationStore | None = None,
        usage_store: UsageStore | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._gateway = gateway
        self._registry = tool_registry
        self._settings = settings
        self._executor = tool_executor
        self._validator = validator or ToolCallValidator(tool_registry)
        self._retriever = retriever
        self._input_guard = input_guard or InputGuard()
        self._output_guard = output_guard or OutputGuard()
        self._sessions = session_store or InMemorySessionStore(
            ttl_seconds=settings.session_ttl_seconds,
            max_turns=settings.session_max_turns,
            history_max_tokens=settings.session_history_max_tokens,
        )
        self._confirmations = confirmation_store or InMemoryConfirmationStore(
            ttl_seconds=settings.confirmation_ttl_seconds
        )
        self._usage = usage_store or InMemoryUsageStore()
        self._metrics = metrics

    async def handle(
        self,
        body: ChatRequest,
        *,
        user: dict[str, Any],
        request_id: str,
        store_id: str,
        access_token: str,
    ) -> ChatResponse:
        started = time.perf_counter()
        user_id = str(user["sub"])
        await self._enforce_usage_cap(store_id)
        refusal = self._guard_input(body)
        if refusal is not None:
            return ChatResponse(
                message=refusal,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="input_guard",
                model="",
            )

        prior_turns = await self._sessions.load_history(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
        )

        tools = list(self._registry.definitions())
        retrieved = await self._retrieve_documentation(body.text)
        messages = [
            ChatMessage(
                role="system",
                content=build_chat_system_prompt(
                    language=body.language,
                    store_id=store_id,
                    tools=tools,
                    documentation=build_documentation_block(
                        retrieved,
                        max_tokens=self._settings.rag_context_max_tokens,
                    ),
                ),
            ),
            *turns_to_messages(prior_turns),
            ChatMessage(role="user", content=body.text),
        ]

        generation = await self._generate_with_optional_parse_repair(
            messages, tools, store_id=store_id
        )
        generations = [generation]

        # Bounded multi-round tool loop: after each round's results the LLM
        # may call the next tools (search -> draft) so multi-step requests
        # finish in ONE user turn instead of asking permission per step.
        conversation = list(messages)
        all_calls: list[ToolCall] = []
        all_results: list[ToolResult] = []
        all_write_results: list[ToolResult] = []
        staged_sensitive = None
        successful_drafts = 0
        executed_signatures: set[tuple[str, str]] = set()
        max_rounds = self._settings.chat_max_tool_rounds

        for round_index in range(max_rounds):
            try:
                tool_calls = self._validator.validate(
                    generation.tool_calls, store_id=store_id
                )
            except AppError as exc:
                if exc.code not in {"TOOL_ARGS_INVALID", "TOOL_NOT_ALLOWED"}:
                    raise
                generation = await self._repair(
                    messages=conversation,
                    tools=tools,
                    previous=generation,
                    store_id=store_id,
                    detail=exc.message,
                )
                generations.append(generation)
                tool_calls = self._validator.validate(
                    generation.tool_calls, store_id=store_id
                )

            if not tool_calls:
                break

            # Guard: never re-execute a (tool, args) pair already run this
            # turn — a looping model must answer instead of burning rounds.
            tool_calls = [
                call
                for call in tool_calls
                if _call_signature(call) not in executed_signatures
            ]
            if not tool_calls:
                generation = await self._continue_turn(
                    conversation=conversation,
                    tools=tools,
                    language=body.language,
                    allow_tools=False,
                )
                generations.append(generation)
                break
            executed_signatures.update(
                _call_signature(call) for call in tool_calls
            )

            read_calls, write_calls, sensitive_calls = _partition_tool_calls(
                tool_calls, registry=self._registry
            )
            read_results = await self._executor.execute_reads(
                read_calls,
                access_token=access_token,
                store_id=store_id,
                session_id=body.session_id,
                user_id=user_id,
            )
            write_results = await self._executor.execute_writes(
                write_calls,
                access_token=access_token,
                store_id=store_id,
                session_id=body.session_id,
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
                self._confirmations,
                user_id=user_id,
                store_id=store_id,
                session_id=body.session_id,
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
            generation = await self._continue_turn(
                conversation=conversation,
                tools=tools,
                language=body.language,
                allow_tools=allow_more_tools,
            )
            generations.append(generation)
            if not allow_more_tools:
                break

        tool_calls = all_calls
        tool_results = all_results

        pending: PendingConfirmation | None = None
        if staged_sensitive is not None:
            pending = pending_to_schema(staged_sensitive)
        else:
            # Latest draft write wins — an update in a later round carries
            # fresher totals than the create before it.
            for result in reversed(all_write_results):
                staged_draft = stage_from_draft_result(
                    self._confirmations,
                    user_id=user_id,
                    store_id=store_id,
                    session_id=body.session_id,
                    result=result,
                )
                if staged_draft is not None:
                    pending = pending_to_schema(staged_draft)
                    break

        reply = _normalize_dashboard_links(generation.content or "")
        reply_provider = generation.provider
        reply_model = generation.model

        message = self._guard_output(
            reply,
            tool_results=tool_results,
            language=body.language,
        )

        await self._sessions.append_turn(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            turn=SessionTurn(
                user_text=body.text,
                assistant_text=message,
                tool_context=self._sessions.compact_tool_context(tool_results),
            ),
        )

        input_tokens = _sum_optional_tokens(
            *(item.input_tokens for item in generations)
        )
        output_tokens = _sum_optional_tokens(
            *(item.output_tokens for item in generations)
        )
        cost_usd = self._estimate_cost_usd(input_tokens, output_tokens)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        await self._usage.record(
            store_id,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            cost_usd=cost_usd or 0.0,
        )
        if self._metrics is not None:
            self._metrics.record_chat(latency_ms)

        self._log_request_metrics(
            request_id=request_id,
            generations=generations,
            retrieved=retrieved,
            tool_calls=tool_calls,
            history_turns=len(prior_turns),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider=reply_provider,
            model=reply_model,
            tool_calls=tool_calls,
            tool_results=tool_results,
            pending_confirmation=pending,
        )

    async def confirm(
        self,
        body: ConfirmRequest,
        *,
        user: dict[str, Any],
        request_id: str,
        store_id: str,
        access_token: str,
    ) -> ChatResponse:
        user_id = str(user["sub"])
        if body.action == "reject":
            record = self._confirmations.reject(
                body.confirmation_id,
                user_id=user_id,
                store_id=store_id,
                session_id=body.session_id,
                draft_id=body.draft_id,
            )
            message = (
                "Release cancelled. The invoice draft is unchanged — "
                "no stock was deducted. "
                f"[Open invoice](/dashboard/invoices/{record.draft_id})"
            )
            await self._sessions.append_turn(
                session_id=body.session_id,
                user_id=user_id,
                store_id=store_id,
                turn=SessionTurn(
                    user_text="[confirm:reject]",
                    assistant_text=message,
                    tool_context=None,
                ),
            )
            return ChatResponse(
                message=message,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="confirmation",
                model="",
            )

        record = self._confirmations.consume(
            body.confirmation_id,
            user_id=user_id,
            store_id=store_id,
            session_id=body.session_id,
            draft_id=body.draft_id,
        )
        tool_call = ToolCall(
            id=f"confirm_{record.confirmation_id[:12]}",
            name=record.tool_name,
            arguments=dict(record.arguments),
        )
        tool_results = await self._executor.execute_confirmations(
            [tool_call],
            access_token=access_token,
            store_id=store_id,
            session_id=body.session_id,
            user_id=user_id,
            confirmation_id=record.confirmation_id,
        )
        result = tool_results[0] if tool_results else None
        if result is not None and result.success:
            open_path = None
            if isinstance(result.data, dict):
                open_path = result.data.get("openPath")
            if not isinstance(open_path, str) or not open_path.strip():
                open_path = f"/dashboard/invoices/{record.draft_id}"
            already = (
                isinstance(result.data, dict)
                and result.data.get("alreadyReleased") is True
            )
            if already:
                message = (
                    "Invoice was already released. "
                    f"[Open invoice]({open_path})"
                )
            else:
                total = None
                if isinstance(record.summary.get("total"), (int, float)):
                    total = record.summary["total"]
                total_bit = f" Total ₹{total}." if total is not None else ""
                message = (
                    f"Invoice released successfully.{total_bit} "
                    f"[Open invoice]({open_path})"
                )
        else:
            err = ""
            if result is not None and isinstance(result.data, dict):
                err = str(result.data.get("message") or result.data.get("code") or "")
            message = (
                "Could not release the invoice"
                + (f": {err}" if err else ".")
                + " Please try again from Invoices."
            )

        message = self._guard_output(
            message,
            tool_results=tool_results,
            language="hi-IN",
        )

        await self._sessions.append_turn(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            turn=SessionTurn(
                user_text="[confirm:approve]",
                assistant_text=message,
                tool_context=self._sessions.compact_tool_context(tool_results),
            ),
        )
        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider="confirmation",
            model="",
            tool_calls=[tool_call],
            tool_results=tool_results,
        )

    def _guard_input(self, body: ChatRequest) -> str | None:
        mode = self._settings.input_guard_mode
        if mode == "off":
            return None
        decision = self._input_guard.evaluate(body.text)
        if decision.allowed:
            return None
        # Log category + matched fragment only — never the full question text.
        logger.warning(
            "Input guard flagged question: category=%s matched=%r mode=%s",
            decision.category,
            (decision.matched or "")[:80],
            mode,
        )
        if mode != "enforce":
            return None
        return get_refusal_message(body.language)

    def _guard_output(
        self,
        message: str,
        *,
        tool_results: list[Any],
        language: str,
    ) -> str:
        mode = self._settings.output_guard_mode
        if mode == "off" or not message:
            return message
        decision = self._output_guard.evaluate(message, tool_results)
        if decision.allowed:
            return message
        # Log category + matched fragment only — never the full response text.
        logger.warning(
            "Output guard flagged response: category=%s matched=%r mode=%s",
            decision.category,
            (decision.matched or "")[:80],
            mode,
        )
        if mode != "enforce":
            return message
        if decision.category == "SECRET_LEAK":
            # Scrub the secret, keep the rest of the answer usable.
            return decision.sanitized_text
        return get_fallback_message(language)

    async def _continue_turn(
        self,
        *,
        conversation: list[ChatMessage],
        tools: list[ToolDefinition],
        language: str,
        allow_tools: bool,
    ) -> GenerationResponse:
        """Post-tool-round generation: either chain further tool calls
        (allow_tools) or force the final grounded answer."""
        instruction = (
            build_continuation_instruction(language=language)
            if allow_tools
            else build_synthesis_instruction(language=language)
        )
        request_messages = [
            *conversation,
            ChatMessage(role="user", content=instruction),
        ]
        return await self._gateway.generate(
            GenerationRequest(
                messages=request_messages,
                temperature=self._settings.chat_temperature,
                max_tokens=self._settings.chat_synthesis_max_tokens,
                tools=tools if allow_tools else None,
                tool_choice="auto" if allow_tools else "none",
            )
        )

    async def _retrieve_documentation(self, question: str) -> list[RetrievedChunk]:
        if self._retriever is None:
            return []
        try:
            return await self._retriever.retrieve(question)
        except AppError:
            logger.warning(
                "RAG retrieval failed; answering without documentation",
                exc_info=True,
            )
            return []

    async def _enforce_usage_cap(self, store_id: str) -> None:
        token_cap = self._settings.tenant_daily_token_cap
        cost_cap = self._settings.tenant_daily_cost_cap_usd
        if not token_cap and not cost_cap:
            return
        usage = await self._usage.get_today(store_id)
        over_tokens = bool(token_cap) and usage.total_tokens >= token_cap
        over_cost = bool(cost_cap) and usage.cost_usd >= cost_cap
        if not over_tokens and not over_cost:
            return
        if self._metrics is not None:
            self._metrics.record_cap_block()
        logger.warning(
            "Usage cap reached: storeId=%s tokens=%d cost_usd=%.4f",
            store_id,
            usage.total_tokens,
            usage.cost_usd,
        )
        raise AppError(
            code="AI_USAGE_CAP_EXCEEDED",
            message="Daily AI usage limit reached for this store",
            status_code=429,
        )

    def _estimate_cost_usd(
        self, input_tokens: int | None, output_tokens: int | None
    ) -> float | None:
        if input_tokens is None or output_tokens is None:
            return None
        return round(
            input_tokens
            * self._settings.chat_input_usd_per_million_tokens
            / 1_000_000
            + output_tokens
            * self._settings.chat_output_usd_per_million_tokens
            / 1_000_000,
            8,
        )

    def _log_request_metrics(
        self,
        *,
        request_id: str,
        generations: list[GenerationResponse],
        retrieved: list[RetrievedChunk],
        tool_calls: list[Any],
        history_turns: int,
        latency_ms: float,
        input_tokens: int | None,
        output_tokens: int | None,
        cost_usd: float | None,
    ) -> None:
        # Doc IDs/scores, tokens, latency, cost — never question or answer
        # text, never user data (rule.md #19).
        generation = generations[0]
        final = generations[-1]
        logger.info(
            "Chat request metrics",
            extra={
                "request_id": request_id,
                "metrics": {
                    "latency_ms": latency_ms,
                    "provider": final.provider,
                    "model": final.model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "tool_turn_input_tokens": generation.input_tokens,
                    "tool_turn_output_tokens": generation.output_tokens,
                    "synthesis_input_tokens": (
                        final.input_tokens if len(generations) > 1 else None
                    ),
                    "synthesis_output_tokens": (
                        final.output_tokens if len(generations) > 1 else None
                    ),
                    "llm_calls": len(generations),
                    "est_cost_usd": cost_usd,
                    "history_turns": history_turns,
                    "retrieved_docs": [
                        {
                            "id": chunk.id,
                            "source": chunk.metadata.get("source", ""),
                            "score": round(chunk.score, 4),
                        }
                        for chunk in retrieved
                    ],
                    "tools_called": [call.name for call in tool_calls],
                },
            },
        )

    async def _generate_with_optional_parse_repair(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        store_id: str,
    ) -> GenerationResponse:
        try:
            return await self._generate(messages, tools)
        except AppError as exc:
            if exc.code != "TOOL_ARGS_INVALID":
                raise
            return await self._repair(
                messages=messages,
                tools=tools,
                previous=None,
                store_id=store_id,
                detail=exc.message,
            )

    async def _generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> GenerationResponse:
        return await self._gateway.generate(
            GenerationRequest(
                messages=messages,
                temperature=self._settings.chat_temperature,
                max_tokens=self._settings.chat_max_tokens,
                tools=tools or None,
                tool_choice="auto" if tools else "none",
            )
        )

    async def _repair(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        previous: GenerationResponse | None,
        store_id: str,
        detail: str | None = None,
    ) -> GenerationResponse:
        if previous is not None and not detail:
            error_lines = self._validator.describe_errors(
                previous.tool_calls, store_id=store_id
            )
            detail = "; ".join(error_lines) or "tool arguments were invalid"
        detail = detail or "tool arguments were invalid"

        repair_messages = list(messages)
        if previous is not None:
            repair_messages.append(
                ChatMessage(
                    role="assistant",
                    content=previous.content
                    or "I attempted tool calls that failed validation.",
                )
            )
        repair_messages.append(
            ChatMessage(
                role="user",
                content=(
                    "Previous tool call validation failed: "
                    f"{detail}. "
                    "Retry with corrected allowlisted tool calls only, "
                    f"using storeId={store_id}."
                ),
            )
        )
        return await self._generate(repair_messages, tools)


def _partition_tool_calls(
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


# openPath values are relative in-app paths; models sometimes "complete"
# them with an invented domain (https://yourappurl.com/dashboard/...),
# which breaks the in-app link. Strip any host in front of /dashboard/.
_DASHBOARD_LINK_RE = re.compile(
    r"(?:https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?"
    r"(/dashboard/[^\s)\]\"']*)"
)


def _normalize_dashboard_links(text: str) -> str:
    return _DASHBOARD_LINK_RE.sub(r"\1", text)


def _call_signature(call: ToolCall) -> tuple[str, str]:
    return (
        call.name,
        json.dumps(call.arguments, sort_keys=True, ensure_ascii=False),
    )


def _sum_optional_tokens(*values: int | None) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)
