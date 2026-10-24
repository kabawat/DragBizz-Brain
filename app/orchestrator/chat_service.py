from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.config import Settings
from app.confirmations import ConfirmationStore, InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.core.store_access import explicit_store_permissions, filter_tool_definitions
from app.executors.tool_executor import ToolExecutor
from app.guards.input_guard import InputGuard
from app.guards.output_guard import (
    _CURRENCY_RE,
    _NUMBER_RE,
    OutputGuard,
    _normalize_amount,
)
from app.guards.prompt_abuse import PromptAbuseLimiter
from app.limits.request_budget import BudgetExceeded, RequestBudget
from app.observability.audit_trail import AuditTrail
from app.observability.evaluations import evaluate_turn_correctness
from app.observability.events import CHAT_REQUEST, LIMIT_BUDGET, emit_event
from app.observability.metrics import MetricsRegistry
from app.observability.middleware_telemetry import (
    trace_context_build,
    trace_intent,
)
from app.observability.pricing import PricingConfig, pricing_from_settings
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.cancel import CancelScope
from app.orchestrator.chat_context import build_chat_context
from app.orchestrator.chat_helpers import (
    get_usage_source,
    normalize_dashboard_links,
    sum_optional_tokens,
)
from app.orchestrator.chat_metrics import log_request_metrics
from app.orchestrator.chat_stream import stream_chat
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import (
    pending_to_schema,
    stage_from_draft_result,
)
from app.orchestrator.conversational_auto import try_fast_conversational_turn
from app.orchestrator.dossier_auto import (
    try_fast_dossier_turn,
    try_fast_due_list,
    try_fast_name_list,
    try_fast_purchase_rank,
    try_fast_store_totals,
)
from app.orchestrator.ledger_auto import try_fast_ledger_turn
from app.orchestrator.token_usage import RequestTokenUsage
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_loop import run_tool_loop
from app.orchestrator.tool_selector import (
    looks_like_field_fill,
    narrow_field_fill_tools,
    resolve_turn_intent,
)
from app.prompts.fallback import (
    get_budget_exceeded_message,
    get_docs_unavailable_message,
    get_fallback_message,
)
from app.prompts.refusal import get_refusal_message
from app.rag.retrieval_cache import NoOpRagCache, RagCache
from app.rag.retriever import Retriever
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    GenerationRequest,
    GenerationResponse,
    PendingConfirmation,
    PublicToolCall,
)
from app.sessions import (
    DurableHistoryStore,
    InMemorySessionStore,
    NoOpHistoryStore,
    SessionStore,
    SessionTurn,
    schedule_persist_turn,
)
from app.tools.registry import ToolRegistry
from app.usage import InMemoryUsageStore, UsageStore

logger = logging.getLogger(__name__)

StreamEmitFn = Callable[[str, dict[str, Any]], Awaitable[None] | None]


def _extract_prior_numbers(
    prior_turns: list[Any], current_user_text: str = ""
) -> set[str]:
    numbers: set[str] = set()
    if current_user_text:
        for match in _NUMBER_RE.finditer(current_user_text):
            numbers.add(_normalize_amount(match.group(0)))
    for turn in prior_turns:
        user_txt = getattr(turn, "user_text", None)
        if user_txt:
            for match in _NUMBER_RE.finditer(user_txt):
                numbers.add(_normalize_amount(match.group(0)))
        tool_ctx = getattr(turn, "tool_context", None)
        if tool_ctx:
            for match in _NUMBER_RE.finditer(tool_ctx):
                numbers.add(_normalize_amount(match.group(0)))
        asst_text = getattr(turn, "assistant_text", None)
        if asst_text:
            for match in _CURRENCY_RE.finditer(asst_text):
                raw = match.group(1) or match.group(2)
                if raw:
                    numbers.add(_normalize_amount(raw))
    return numbers


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
        rag_cache: RagCache | None = None,
        input_guard: InputGuard | None = None,
        output_guard: OutputGuard | None = None,
        prompt_abuse_limiter: PromptAbuseLimiter | None = None,
        session_store: SessionStore | None = None,
        history_store: DurableHistoryStore | None = None,
        confirmation_store: ConfirmationStore | None = None,
        usage_store: UsageStore | None = None,
        metrics: MetricsRegistry | None = None,
        audit_trail: AuditTrail | None = None,
        pricing: PricingConfig | None = None,
    ) -> None:
        self._gateway = gateway
        self._registry = tool_registry
        self._settings = settings
        self._executor = tool_executor
        self._validator = validator or ToolCallValidator(tool_registry)
        self._retriever = retriever
        self._rag_cache: RagCache = rag_cache or NoOpRagCache()
        self._input_guard = input_guard or InputGuard()
        self._output_guard = output_guard or OutputGuard()
        self._prompt_abuse = prompt_abuse_limiter or PromptAbuseLimiter()
        self._sessions = session_store or InMemorySessionStore(
            ttl_seconds=settings.session.ttl_seconds,
            max_turns=settings.session.max_turns,
            history_max_tokens=settings.session.history_max_tokens,
        )
        self._history: DurableHistoryStore = history_store or NoOpHistoryStore()
        self._confirmations = confirmation_store or InMemoryConfirmationStore(
            ttl_seconds=settings.session.confirmation_ttl_seconds
        )
        self._usage = usage_store or InMemoryUsageStore()
        self._metrics = metrics
        self._audit_trail = audit_trail
        self._pricing = pricing or pricing_from_settings(settings)

    async def handle(
        self,
        body: ChatRequest,
        *,
        user: dict[str, Any],
        request_id: str,
        store_id: str,
        access_token: str,
        cancel: CancelScope | None = None,
        emit: StreamEmitFn | None = None,
    ) -> ChatResponse:
        started = time.perf_counter()
        user_id = str(user["sub"])
        agency_id = str(user["agencyId"]).strip() if user.get("agencyId") else None
        tenant_id = str(user["tenant"]).strip().lower() if user.get("tenant") else None
        refusal = await self._guard_input(body, user_id=user_id, store_id=store_id)
        if refusal is not None:
            return ChatResponse(
                message=refusal,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="input_guard",
                model="",
            )
        await self._enforce_usage_cap(store_id)

        user_name = str(user.get("name") or user.get("given_name") or "")
        fast_conv = try_fast_conversational_turn(
            body.text,
            language=body.language,
            user_name=user_name,
        )
        if fast_conv is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=set(),
                provider="fast_conversational",
                message=fast_conv.message,
                tool_calls=[],
                tool_results=[],
                pending_confirmation=None,
            )

        if emit is not None:
            res = emit(
                "agent.progress",
                {"stage": "understanding", "label": "Understanding your request…"},
            )
            if res is not None:
                await res

        available = {definition.name for definition in self._registry.definitions()}
        permissions = explicit_store_permissions(user, store_id)
        if permissions is not None:
            available = {
                definition.name
                for definition in filter_tool_definitions(
                    self._registry.definitions(), permissions
                )
            }
        prior_turns = await self._sessions.load_history(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
        )
        prior_numbers = _extract_prior_numbers(prior_turns, current_user_text=body.text)
        with trace_intent(len(body.text)):
            intent = resolve_turn_intent(
                body.text,
                available=available,
                prior_user_texts=[turn.user_text for turn in prior_turns],
                use_domain_routing=self._settings.chat.domain_routing_enabled,
            )
        tool_names = intent.tool_names
        field_fill = looks_like_field_fill(body.text)
        if field_fill:
            tool_names = narrow_field_fill_tools(tool_names)
        tools = list(self._registry.definitions_for(tool_names))
        allowed_names = frozenset(tool.name for tool in tools)

        if cancel is not None:
            cancel.raise_if_cancelled()
        fast_ledger = await try_fast_ledger_turn(
            question=body.text,
            language=body.language,
            store_id=store_id,
            access_token=access_token,
            session_id=body.session_id,
            user_id=user_id,
            allowed_names=allowed_names,
            executor=self._executor,
            confirmations=self._confirmations,
            audit_trail=self._audit_trail,
            metrics=self._metrics,
        )
        if fast_ledger is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=prior_numbers,
                provider="fast_ledger",
                message=fast_ledger.message,
                tool_calls=fast_ledger.tool_calls,
                tool_results=fast_ledger.tool_results,
                pending_confirmation=fast_ledger.pending_confirmation,
            )
        fast_names = await try_fast_name_list(
            question=body.text,
            language=body.language,
            store_id=store_id,
            access_token=access_token,
            session_id=body.session_id,
            user_id=user_id,
            allowed_names=allowed_names,
            executor=self._executor,
        )
        if fast_names is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=prior_numbers,
                provider="fast_names",
                message=fast_names.message,
                tool_calls=fast_names.tool_calls,
                tool_results=fast_names.tool_results,
                pending_confirmation=None,
            )
        fast_purchases = await try_fast_purchase_rank(
            question=body.text,
            language=body.language,
            store_id=store_id,
            access_token=access_token,
            session_id=body.session_id,
            user_id=user_id,
            allowed_names=allowed_names,
            executor=self._executor,
        )
        if fast_purchases is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=prior_numbers,
                provider="fast_purchases",
                message=fast_purchases.message,
                tool_calls=fast_purchases.tool_calls,
                tool_results=fast_purchases.tool_results,
                pending_confirmation=None,
            )
        fast_dues = await try_fast_due_list(
            question=body.text,
            language=body.language,
            store_id=store_id,
            access_token=access_token,
            session_id=body.session_id,
            user_id=user_id,
            allowed_names=allowed_names,
            executor=self._executor,
        )
        if fast_dues is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=prior_numbers,
                provider="fast_dues",
                message=fast_dues.message,
                tool_calls=fast_dues.tool_calls,
                tool_results=fast_dues.tool_results,
                pending_confirmation=None,
            )
        fast_totals = await try_fast_store_totals(
            question=body.text,
            language=body.language,
            store_id=store_id,
            access_token=access_token,
            session_id=body.session_id,
            user_id=user_id,
            allowed_names=allowed_names,
            executor=self._executor,
        )
        if fast_totals is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=prior_numbers,
                provider="fast_totals",
                message=fast_totals.message,
                tool_calls=fast_totals.tool_calls,
                tool_results=fast_totals.tool_results,
                pending_confirmation=None,
            )
        fast_dossier = await try_fast_dossier_turn(
            question=body.text,
            language=body.language,
            store_id=store_id,
            access_token=access_token,
            session_id=body.session_id,
            user_id=user_id,
            allowed_names=allowed_names,
            executor=self._executor,
        )
        if fast_dossier is not None:
            return await self._finish_deterministic(
                body=body,
                user_id=user_id,
                request_id=request_id,
                store_id=store_id,
                started=started,
                prior_numbers=prior_numbers,
                provider="fast_dossier",
                message=fast_dossier.message,
                tool_calls=fast_dossier.tool_calls,
                tool_results=fast_dossier.tool_results,
                pending_confirmation=None,
            )

        with trace_context_build():
            context = await build_chat_context(
                sessions=self._sessions,
                retriever=self._retriever,
                settings=self._settings,
                question=body.text,
                language=body.language,
                session_id=body.session_id,
                user_id=user_id,
                store_id=store_id,
                tools=tools,
                routing=intent.routing,
                rag_cache=self._rag_cache,
                metrics=self._metrics,
                prior_turns=prior_turns,
            )
        if context.docs_unavailable:
            await self._prompt_abuse.clear(user_id=user_id, store_id=store_id)
            message = get_docs_unavailable_message(body.language)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            if self._metrics is not None:
                self._metrics.record_chat(latency_ms, error=True)
            emit_event(
                CHAT_REQUEST,
                outcome="docs_unavailable",
                metrics={"latency_ms": latency_ms},
            )
            return ChatResponse(
                message=message,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="rag",
                model="",
            )

        budget = RequestBudget(
            max_model_calls=self._settings.limits.max_model_calls,
            max_tool_calls=self._settings.limits.max_tool_calls,
            max_estimated_input_tokens=(
                self._settings.limits.max_estimated_input_tokens
            ),
            max_estimated_output_tokens=(
                self._settings.limits.max_estimated_output_tokens
            ),
            deadline_seconds=self._settings.limits.request_deadline_seconds,
        )
        token_usage = RequestTokenUsage()
        if self._metrics is not None:
            self._metrics.record_context_estimate(
                system=context.token_breakdown.system,
                history=context.token_breakdown.history,
                tool_schemas=context.token_breakdown.tools,
                rag=context.token_breakdown.rag,
            )

        def _describe_errors(tool_calls: list, sid: str) -> list[str]:
            return self._validator.describe_errors(
                tool_calls,
                store_id=sid,
                allowed_names=allowed_names,
                agency_id=agency_id,
                tenant_id=tenant_id,
            )

        try:
            if cancel is not None:
                cancel.raise_if_cancelled()
            max_tokens = self._settings.chat.max_tokens
            if field_fill:
                max_tokens = min(max_tokens, self._settings.chat.synthesis_max_tokens)
            elif tools:
                max_tokens = min(max_tokens, 512)
            else:
                max_tokens = max(max_tokens, 2048)
            if not tools and emit is not None:
                collected_chunks: list[str] = []
                async for chunk in self._gateway.generate_stream(
                    GenerationRequest(
                        messages=context.messages,
                        temperature=self._settings.chat.temperature,
                        max_tokens=max_tokens,
                        tools=None,
                        tool_choice="none",
                    ),
                    budget=budget,
                    token_usage=token_usage,
                    call_type="initial",
                ):
                    collected_chunks.append(chunk)
                    res = emit("assistant.delta", {"text": chunk})
                    if res is not None:
                        await res
                generation = GenerationResponse(
                    provider="stream",
                    model="",
                    content="".join(collected_chunks),
                    tool_calls=[],
                )
            else:
                generation = await self._gateway.generate_with_optional_parse_repair(
                    context.messages,
                    tools,
                    store_id=store_id,
                    temperature=self._settings.chat.temperature,
                    max_tokens=max_tokens,
                    describe_errors=_describe_errors,
                    budget=budget,
                    token_usage=token_usage,
                )

            outcome = await run_tool_loop(
                gateway=self._gateway,
                validator=self._validator,
                registry=self._registry,
                executor=self._executor,
                confirmations=self._confirmations,
                settings=self._settings,
                generation=generation,
                messages=context.messages,
                tools=tools,
                language=body.language,
                store_id=store_id,
                access_token=access_token,
                session_id=body.session_id,
                user_id=user_id,
                agency_id=agency_id,
                tenant_id=tenant_id,
                budget=budget,
                audit_trail=self._audit_trail,
                metrics=self._metrics,
                cancel=cancel,
                emit=None if not tools else emit,
                token_usage=token_usage,
            )
        except asyncio.CancelledError:
            if self._metrics is not None:
                self._metrics.record_cancel()
            raise
        except BudgetExceeded as exc:
            logger.warning("BudgetExceeded for request_id=%s: %s", request_id, exc)
            await self._prompt_abuse.clear(user_id=user_id, store_id=store_id)
            if self._metrics is not None:
                self._metrics.record_budget_exceeded()
            emit_event(LIMIT_BUDGET)
            message = get_budget_exceeded_message(body.language)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            if self._metrics is not None:
                self._metrics.record_chat(latency_ms, error=True)
            return ChatResponse(
                message=message,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="budget",
                model="",
            )
        except AppError as exc:
            if exc.code in {"TOOL_ARGS_INVALID", "TOOL_NOT_ALLOWED"}:
                strikes = await self._prompt_abuse.record_violation(
                    user_id=user_id, store_id=store_id
                )
                if strikes >= self._prompt_abuse.threshold:
                    await self._sessions.clear_session(
                        session_id=body.session_id,
                        user_id=user_id,
                        store_id=store_id,
                    )
                    return self._prompt_lock_response(
                        body=body,
                        user_id=user_id,
                        request_id=request_id,
                    )
            else:
                await self._prompt_abuse.clear(user_id=user_id, store_id=store_id)
            logger.exception("Chat generation failed; returning fallback")
            message = get_fallback_message(body.language)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            if self._metrics is not None:
                self._metrics.record_chat(latency_ms, error=True)
            return ChatResponse(
                message=message,
                session_id=body.session_id,
                request_id=request_id,
                user_id=user_id,
                provider="error",
                model="",
            )

        pending: PendingConfirmation | None = None
        if outcome.staged_sensitive is not None:
            pending = pending_to_schema(outcome.staged_sensitive)
        else:
            # Prefer the latest draft write in this turn.
            for result in reversed(outcome.all_write_results):
                staged_draft = await stage_from_draft_result(
                    self._confirmations,
                    user_id=user_id,
                    store_id=store_id,
                    session_id=body.session_id,
                    result=result,
                    audit_trail=self._audit_trail,
                    metrics=self._metrics,
                )
                if staged_draft is not None:
                    pending = pending_to_schema(staged_draft)
                    break

        if pending is not None and pending.summary:
            for val in pending.summary.values():
                for m in _NUMBER_RE.finditer(str(val)):
                    prior_numbers.add(_normalize_amount(m.group(0)))
        if outcome.generation.tool_calls:
            for tc in outcome.generation.tool_calls:
                args_dict = getattr(tc, "arguments", {}) or {}
                if isinstance(args_dict, dict):
                    for val in args_dict.values():
                        for m in _NUMBER_RE.finditer(str(val)):
                            prior_numbers.add(_normalize_amount(m.group(0)))

        reply = normalize_dashboard_links(outcome.generation.content or "")
        message = self._guard_output(
            reply,
            tool_results=outcome.all_results,
            language=body.language,
            prior_numbers=prior_numbers,
            protected_prompt=(
                context.messages[0].content if context.messages else None
            ),
        )
        if not message.strip():
            message = get_fallback_message(body.language)

        await self._sessions.append_turn(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            turn=SessionTurn(
                user_text=body.text,
                assistant_text=message,
                tool_context=self._sessions.compact_tool_context(outcome.all_results),
            ),
        )
        schedule_persist_turn(
            self._history,
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            user_text=body.text,
            assistant_text=message,
            tool_results=outcome.all_results,
        )
        await self._prompt_abuse.clear(user_id=user_id, store_id=store_id)

        # Prefer tracker totals when present (includes retries).
        if token_usage.model_calls:
            input_tokens = token_usage.input_tokens
            output_tokens = token_usage.output_tokens
            usage_source = token_usage.usage_source
        else:
            usage_source = get_usage_source(outcome.generations)
            input_tokens = sum_optional_tokens(
                *(item.input_tokens for item in outcome.generations)
            )
            output_tokens = sum_optional_tokens(
                *(item.output_tokens for item in outcome.generations)
            )
        cost = self._pricing.compute_chat_cost(
            provider=outcome.generation.provider,
            model=outcome.generation.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_source=("actual" if usage_source == "actual" else "estimated"),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        if usage_source == "actual" and input_tokens is not None:
            await self._usage.record(
                store_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens or 0,
                cost_usd=cost.cost_usd or 0.0,
            )
        if self._metrics is not None:
            self._metrics.record_chat(latency_ms, error=False)

        log_request_metrics(
            generations=outcome.generations,
            retrieved=context.retrieved,
            tool_calls=outcome.all_calls,
            history_turns=len(context.prior_turns),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            token_breakdown=context.token_breakdown,
            rag_cache_hit=context.rag_cache_hit,
            outcome="ok",
            token_usage=token_usage,
            compacted_tokens=outcome.compacted_tokens,
            removed_schema_tokens=outcome.removed_schema_tokens,
            removed_result_tokens=outcome.removed_result_tokens,
        )

        evaluate_turn_correctness(
            tool_calls=outcome.all_calls,
            tool_results=outcome.all_results,
            message=message,
        )

        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider=outcome.generation.provider,
            model=outcome.generation.model,
            tool_calls=[
                PublicToolCall(id=call.id, name=call.name) for call in outcome.all_calls
            ],
            tool_results=outcome.all_results,
            pending_confirmation=pending,
        )

    async def handle_stream(
        self,
        body: ChatRequest,
        *,
        user: dict[str, Any],
        request_id: str,
        store_id: str,
        access_token: str,
        cancel: CancelScope | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        async for event in stream_chat(
            self.handle,
            body,
            user=user,
            request_id=request_id,
            store_id=store_id,
            access_token=access_token,
            metrics=self._metrics,
            cancel=cancel,
        ):
            yield event

    async def confirm(
        self,
        body: ConfirmRequest,
        *,
        user: dict[str, Any],
        request_id: str,
        store_id: str,
        access_token: str,
    ) -> ChatResponse:
        return await handle_confirm(
            body,
            user_id=str(user["sub"]),
            request_id=request_id,
            store_id=store_id,
            access_token=access_token,
            confirmations=self._confirmations,
            sessions=self._sessions,
            executor=self._executor,
            guard_output=self._guard_output,
            audit_trail=self._audit_trail,
            metrics=self._metrics,
            history=self._history,
        )

    async def _finish_deterministic(
        self,
        *,
        body: ChatRequest,
        user_id: str,
        request_id: str,
        store_id: str,
        started: float,
        prior_numbers: set[str],
        provider: str,
        message: str,
        tool_calls: list[Any],
        tool_results: list[Any],
        pending_confirmation: PendingConfirmation | None,
    ) -> ChatResponse:
        if pending_confirmation is not None and pending_confirmation.summary:
            for val in pending_confirmation.summary.values():
                for m in _NUMBER_RE.finditer(str(val)):
                    prior_numbers.add(_normalize_amount(m.group(0)))
        if tool_calls:
            for tc in tool_calls:
                args = (
                    getattr(tc, "arguments", {})
                    if not isinstance(tc, dict)
                    else tc.get("arguments", {})
                )
                if isinstance(args, dict):
                    for val in args.values():
                        for m in _NUMBER_RE.finditer(str(val)):
                            prior_numbers.add(_normalize_amount(m.group(0)))

        guarded = self._guard_output(
            message,
            tool_results=tool_results,
            language=body.language,
            prior_numbers=prior_numbers,
        )
        evaluate_turn_correctness(
            tool_calls=tool_calls,
            tool_results=tool_results,
            message=guarded,
        )
        await self._sessions.append_turn(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            turn=SessionTurn(
                user_text=body.text,
                assistant_text=guarded,
                tool_context=self._sessions.compact_tool_context(tool_results),
            ),
        )
        schedule_persist_turn(
            self._history,
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            user_text=body.text,
            assistant_text=guarded,
            tool_results=tool_results,
        )
        await self._prompt_abuse.clear(user_id=user_id, store_id=store_id)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if self._metrics is not None:
            self._metrics.record_chat(latency_ms, error=False)
        emit_event(
            CHAT_REQUEST,
            outcome="ok",
            metrics={
                "latency_ms": latency_ms,
                "outcome": "ok",
                "provider": provider,
                "model": "",
                "model_calls": 0,
                "tools_called": [call.name for call in tool_calls],
            },
        )
        return ChatResponse(
            message=guarded,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider=provider,
            model="",
            tool_calls=[
                PublicToolCall(id=call.id, name=call.name) for call in tool_calls
            ],
            tool_results=tool_results,
            pending_confirmation=pending_confirmation,
        )

    async def _guard_input(
        self, body: ChatRequest, *, user_id: str, store_id: str
    ) -> str | None:
        if await self._prompt_abuse.is_locked(user_id=user_id, store_id=store_id):
            return (
                "Chat is temporarily paused after repeated invalid prompts. "
                "Please try again in a few minutes."
            )
        mode = self._settings.guards.input_mode
        decision = self._input_guard.evaluate(body.text)
        if decision.allowed:
            return None
        # Log the classification only; do not copy attacker text into logs.
        logger.warning(
            "Input guard flagged question: category=%s mode=%s",
            decision.category,
            mode,
        )
        must_block = decision.category == "PROMPT_INJECTION" or mode == "enforce"
        if not must_block or (
            mode == "off" and decision.category != "PROMPT_INJECTION"
        ):
            return None
        strikes = await self._prompt_abuse.record_violation(
            user_id=user_id, store_id=store_id
        )
        if strikes >= self._prompt_abuse.threshold:
            await self._sessions.clear_session(
                session_id=body.session_id,
                user_id=user_id,
                store_id=store_id,
            )
            return (
                "Chat is temporarily paused after repeated invalid prompts. "
                "Please try again in a few minutes."
            )
        if decision.category == "PROMPT_INJECTION":
            return (
                "I can only assist with store operations, sales, stock, and invoices."
            )
        return get_refusal_message(body.language)

    def _prompt_lock_response(
        self, *, body: ChatRequest, user_id: str, request_id: str
    ) -> ChatResponse:
        return ChatResponse(
            message=(
                "Chat is temporarily paused after repeated invalid prompts. "
                "Please try again in a few minutes."
            ),
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider="input_guard",
            model="",
        )

    def _guard_output(
        self,
        message: str,
        *,
        tool_results: list[Any],
        language: str,
        prior_numbers: set[str] | None = None,
        protected_prompt: str | None = None,
    ) -> str:
        mode = self._settings.guards.output_mode
        if not message:
            return message
        decision = self._output_guard.evaluate(
            message,
            tool_results,
            prior_numbers=prior_numbers,
            protected_prompt=protected_prompt,
        )
        if decision.allowed:
            return message
        # Log category/match only, not full response.
        logger.warning(
            "Output guard flagged response: category=%s matched=%r mode=%s",
            decision.category,
            (decision.matched or "")[:80],
            mode,
        )
        hard_block = decision.category in {
            "SECRET_LEAK",
            "INTERNAL_DISCLOSURE",
            "RAW_JSON",
        }
        if mode == "off" and not hard_block:
            return message
        if mode != "enforce" and not hard_block:
            return message
        if decision.category == "SECRET_LEAK":
            # Scrub leaked secret; keep the rest.
            return decision.sanitized_text
        return get_fallback_message(language)

    async def _enforce_usage_cap(self, store_id: str) -> None:
        token_cap = self._settings.limits.tenant_daily_token_cap
        cost_cap = self._settings.limits.tenant_daily_cost_cap_usd
        if not token_cap and not cost_cap:
            return
        usage = await self._usage.get_today(store_id)
        over_tokens = bool(token_cap) and usage.total_tokens >= token_cap
        over_cost = bool(cost_cap) and usage.cost_usd >= cost_cap
        if not over_tokens and not over_cost:
            return
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
