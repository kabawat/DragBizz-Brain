from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.config import Settings
from app.confirmations import ConfirmationStore, InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.limits.request_budget import BudgetExceeded, RequestBudget
from app.observability.audit_trail import AuditTrail
from app.observability.events import CHAT_REQUEST, LIMIT_BUDGET, emit_event
from app.observability.metrics import MetricsRegistry
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
from app.orchestrator.token_usage import RequestTokenUsage
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_loop import run_tool_loop
from app.orchestrator.tool_selector import resolve_turn_intent
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
    PendingConfirmation,
)
from app.sessions import (
    DurableHistoryStore,
    InMemorySessionStore,
    NoOpHistoryStore,
    SessionStore,
    SessionTurn,
    persist_turn_safe,
)
from app.tools.registry import ToolRegistry
from app.usage import InMemoryUsageStore, UsageStore

logger = logging.getLogger(__name__)

StreamEmitFn = Callable[[str, dict[str, Any]], Awaitable[None] | None]


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

        available = {definition.name for definition in self._registry.definitions()}
        # Capability set comes from the current user message only.
        intent = resolve_turn_intent(body.text, available=available)
        tools = list(self._registry.definitions_for(intent.tool_names))
        allowed_names = frozenset(tool.name for tool in tools)
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
        )
        if context.docs_unavailable:
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
                tool_calls, store_id=sid, allowed_names=allowed_names
            )

        try:
            if cancel is not None:
                cancel.raise_if_cancelled()
            generation = await self._gateway.generate_with_optional_parse_repair(
                context.messages,
                tools,
                store_id=store_id,
                temperature=self._settings.chat.temperature,
                max_tokens=self._settings.chat.max_tokens,
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
                budget=budget,
                audit_trail=self._audit_trail,
                metrics=self._metrics,
                cancel=cancel,
                emit=emit,
                token_usage=token_usage,
            )
        except asyncio.CancelledError:
            if self._metrics is not None:
                self._metrics.record_cancel()
            raise
        except BudgetExceeded:
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

        pending: PendingConfirmation | None = None
        if outcome.staged_sensitive is not None:
            pending = pending_to_schema(outcome.staged_sensitive)
        else:
            # Latest draft write wins — an update in a later round carries
            # fresher totals than the create before it.
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

        reply = normalize_dashboard_links(outcome.generation.content or "")
        message = self._guard_output(
            reply,
            tool_results=outcome.all_results,
            language=body.language,
        )

        await self._sessions.append_turn(
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            turn=SessionTurn(
                user_text=body.text,
                assistant_text=message,
                tool_context=self._sessions.compact_tool_context(
                    outcome.all_results
                ),
            ),
        )
        await persist_turn_safe(
            self._history,
            session_id=body.session_id,
            user_id=user_id,
            store_id=store_id,
            user_text=body.text,
            assistant_text=message,
            tool_results=outcome.all_results,
        )

        # Tracker includes retries/fallback; generations omit those attempts.
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
            usage_source=(
                "actual" if usage_source == "actual" else "estimated"
            ),
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

        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=user_id,
            provider=outcome.generation.provider,
            model=outcome.generation.model,
            tool_calls=outcome.all_calls,
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

    def _guard_input(self, body: ChatRequest) -> str | None:
        mode = self._settings.guards.input_mode
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
        mode = self._settings.guards.output_mode
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
