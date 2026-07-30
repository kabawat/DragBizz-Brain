from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.config import Settings
from app.confirmations import ConfirmationStore, InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.observability.metrics import MetricsRegistry
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_context import build_chat_context
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import (
    pending_to_schema,
    stage_from_draft_result,
)
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_loop import run_tool_loop
from app.prompts.fallback import get_fallback_message
from app.prompts.refusal import get_refusal_message
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    GenerationResponse,
    PendingConfirmation,
)
from app.sessions import (
    InMemorySessionStore,
    SessionStore,
    SessionTurn,
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
        confirmation_store: ConfirmationStore | None = None,
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

        tools = list(self._registry.definitions())
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
        )

        def _describe_errors(tool_calls: list, sid: str) -> list[str]:
            return self._validator.describe_errors(tool_calls, store_id=sid)

        generation = await self._gateway.generate_with_optional_parse_repair(
            context.messages,
            tools,
            store_id=store_id,
            temperature=self._settings.chat_temperature,
            max_tokens=self._settings.chat_max_tokens,
            describe_errors=_describe_errors,
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
                )
                if staged_draft is not None:
                    pending = pending_to_schema(staged_draft)
                    break

        reply = _normalize_dashboard_links(outcome.generation.content or "")
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

        input_tokens = _sum_optional_tokens(
            *(item.input_tokens for item in outcome.generations)
        )
        output_tokens = _sum_optional_tokens(
            *(item.output_tokens for item in outcome.generations)
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
            generations=outcome.generations,
            retrieved=context.retrieved,
            tool_calls=outcome.all_calls,
            history_turns=len(context.prior_turns),
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
            provider=outcome.generation.provider,
            model=outcome.generation.model,
            tool_calls=outcome.all_calls,
            tool_results=outcome.all_results,
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


# openPath values are relative in-app paths; models sometimes "complete"
# them with an invented domain (https://yourappurl.com/dashboard/...),
# which breaks the in-app link. Strip any host in front of /dashboard/.
_DASHBOARD_LINK_RE = re.compile(
    r"(?:https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?"
    r"(/dashboard/[^\s)\]\"']*)"
)


def _normalize_dashboard_links(text: str) -> str:
    return _DASHBOARD_LINK_RE.sub(r"\1", text)


def _sum_optional_tokens(*values: int | None) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)
