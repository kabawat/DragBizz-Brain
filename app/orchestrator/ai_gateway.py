from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.core.exceptions import AppError
from app.limits.circuit_breaker import CircuitBreaker
from app.limits.request_budget import RequestBudget
from app.observability.events import MODEL_ATTEMPT, emit_event
from app.observability.metrics import MetricsRegistry
from app.observability.middleware_telemetry import trace_llm_call
from app.orchestrator.model_config import ModelSelectionStore
from app.orchestrator.model_router import ModelRouter
from app.orchestrator.token_usage import RequestTokenUsage
from app.prompts.synthesis import (
    build_continuation_instruction,
    build_synthesis_instruction,
)
from app.providers.openai_compatible import (
    CHEAPER_PROVIDER_NAME,
    GOOGLE_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
)
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

_FALLBACK_PROVIDER = {
    OPENAI_PROVIDER_NAME: CHEAPER_PROVIDER_NAME,
    GOOGLE_PROVIDER_NAME: OPENAI_PROVIDER_NAME,
    CHEAPER_PROVIDER_NAME: OPENAI_PROVIDER_NAME,
}

DescribeErrorsFn = Callable[[list[ToolCall], str], list[str]]


class AiGateway:
    """Single entry point to LLM providers: applies the admin-selected
    provider/model, builds chat/repair/synthesis turns, and records
    provider latency/error metrics."""

    def __init__(
        self,
        model_router: ModelRouter,
        *,
        selection_store: ModelSelectionStore | None = None,
        metrics: MetricsRegistry | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._model_router = model_router
        self._selection_store = selection_store
        self._metrics = metrics
        self._breaker = breaker or CircuitBreaker(name="provider")

    async def generate(
        self,
        request: GenerationRequest,
        *,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
        call_type: str = "generate",
        round: int = 0,
    ) -> GenerationResponse:
        provider, model = await self._resolve()
        if model is not None:
            request = request.model_copy(update={"model": model})

        return await self._generate_with_retry_fallback(
            provider,
            request,
            budget=budget,
            token_usage=token_usage,
            call_type=call_type,
            round=round,
        )

    async def generate_stream(
        self,
        request: GenerationRequest,
        *,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
        call_type: str = "stream",
        round: int = 0,
    ) -> AsyncIterator[str]:
        provider, model = await self._resolve()
        if model is not None:
            request = request.model_copy(update={"model": model})

        self._breaker.allow()
        if budget is not None:
            budget.begin_model_call(allow_synthesis=(call_type == "synthesize"))

        yielded_any = False
        started = time.perf_counter()
        collected_text: list[str] = []

        try:
            async for chunk in provider.generate_stream(request):
                yielded_any = True
                collected_text.append(chunk)
                yield chunk
        except Exception:
            if not yielded_any:
                self._record(started, error=True, retry=False, fallback=False)
                fallback = self._fallback_for(provider)
                if fallback is not None:
                    logger.warning(
                        "Streaming provider %s failed before tokens; switching to %s",
                        provider.name,
                        fallback.name,
                    )
                    fallback_request = request.model_copy(update={"model": None})
                    self._breaker.allow()
                    try:
                        async for chunk in fallback.generate_stream(fallback_request):
                            yielded_any = True
                            collected_text.append(chunk)
                            yield chunk
                    except Exception:
                        self._record(started, error=True, retry=False, fallback=True)
                        raise
                    self._record(started, error=False, retry=False, fallback=True)
                    self._breaker.record_success()
                    return
            self._record(started, error=True, retry=False, fallback=False)
            raise

        self._record(started, error=False, retry=False, fallback=False)
        self._breaker.record_success()

        full_text = "".join(collected_text)
        from app.rag.chunker import estimate_tokens

        output_tokens = estimate_tokens(full_text)
        if budget is not None:
            budget.record_tokens(output_tokens=output_tokens)
        if token_usage is not None:
            entry = token_usage.record(
                model=request.model or "",
                call_type=call_type,
                round=round,
                output_tokens=output_tokens,
                provider=provider.name,
            )
            if self._metrics is not None:
                self._metrics.record_token_usage(
                    input_tokens=None,
                    output_tokens=output_tokens,
                    usage_source=entry.usage_source,
                )

    async def generate_chat_turn(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        temperature: float,
        max_tokens: int,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
        call_type: str = "initial",
        round: int = 0,
    ) -> GenerationResponse:
        return await self.generate(
            GenerationRequest(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools or None,
                tool_choice="auto" if tools else "none",
            ),
            budget=budget,
            token_usage=token_usage,
            call_type=call_type,
            round=round,
        )

    async def generate_with_optional_parse_repair(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        store_id: str,
        temperature: float,
        max_tokens: int,
        describe_errors: DescribeErrorsFn,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
    ) -> GenerationResponse:
        try:
            return await self.generate_chat_turn(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
                budget=budget,
                token_usage=token_usage,
                call_type="initial",
                round=0,
            )
        except AppError as exc:
            if exc.code != "TOOL_ARGS_INVALID":
                raise
            try:
                return await self.repair_tool_calls(
                    messages=messages,
                    tools=tools,
                    previous=None,
                    store_id=store_id,
                    detail=exc.message,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    describe_errors=describe_errors,
                    budget=budget,
                    token_usage=token_usage,
                    round=0,
                )
            except AppError as repair_exc:
                if repair_exc.code != "TOOL_ARGS_INVALID":
                    raise
                # Avoid crashing an already-open SSE stream on bad tool JSON.
                return GenerationResponse(
                    provider="repair_failed",
                    model="",
                    content="",
                    tool_calls=[],
                )

    async def repair_tool_calls(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        previous: GenerationResponse | None,
        store_id: str,
        detail: str | None = None,
        temperature: float,
        max_tokens: int,
        describe_errors: DescribeErrorsFn,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
        round: int = 0,
    ) -> GenerationResponse:
        if previous is not None and not detail:
            error_lines = describe_errors(previous.tool_calls, store_id)
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
        return await self.generate_chat_turn(
            repair_messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
            budget=budget,
            token_usage=token_usage,
            call_type="repair",
            round=round,
        )

    async def continue_or_synthesize(
        self,
        conversation: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        language: str,
        allow_tools: bool,
        temperature: float,
        max_tokens: int,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
        round: int = 0,
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
        return await self.generate(
            GenerationRequest(
                messages=request_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools if allow_tools else None,
                tool_choice="auto" if allow_tools else "none",
            ),
            budget=budget,
            token_usage=token_usage,
            call_type="continue" if allow_tools else "synthesize",
            round=round,
        )

    async def continue_or_synthesize_stream(
        self,
        conversation: list[ChatMessage],
        *,
        language: str,
        temperature: float,
        max_tokens: int,
        budget: RequestBudget | None = None,
        token_usage: RequestTokenUsage | None = None,
        round: int = 0,
    ) -> AsyncIterator[str]:
        instruction = build_synthesis_instruction(language=language)
        request_messages = [
            *conversation,
            ChatMessage(role="user", content=instruction),
        ]
        async for chunk in self.generate_stream(
            GenerationRequest(
                messages=request_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=None,
                tool_choice="none",
            ),
            budget=budget,
            token_usage=token_usage,
            call_type="synthesize",
            round=round,
        ):
            yield chunk

    async def _generate_with_retry_fallback(
        self,
        provider: Any,
        request: GenerationRequest,
        *,
        budget: RequestBudget | None,
        token_usage: RequestTokenUsage | None = None,
        call_type: str = "generate",
        round: int = 0,
    ) -> GenerationResponse:
        """breaker → attempt → retryable retry → fallback → final failure."""
        try:
            self._breaker.allow()
        except AppError:
            fallback = self._fallback_for(provider)
            if fallback is not None:
                logger.warning(
                    "Provider %s circuit breaker is open; switching to fallback %s",
                    provider.name,
                    fallback.name,
                )
                fallback_request = request.model_copy(update={"model": None})
                return await self._budgeted_call(
                    fallback,
                    fallback_request,
                    budget=budget,
                    token_usage=token_usage,
                    call_type=call_type,
                    round=round,
                    retry=False,
                    fallback=True,
                )
            raise

        try:
            return await self._budgeted_call(
                provider,
                request,
                budget=budget,
                token_usage=token_usage,
                call_type=call_type,
                round=round,
                retry=False,
                fallback=False,
            )
        except AppError as exc:
            if exc.retryable:
                self._breaker.record_failure()
            else:
                raise

            # At most one more attempt on the same provider if budget remains.
            try:
                self._breaker.allow()
                return await self._budgeted_call(
                    provider,
                    request,
                    budget=budget,
                    token_usage=token_usage,
                    call_type=call_type,
                    round=round,
                    retry=True,
                    fallback=False,
                )
            except AppError as retry_exc:
                if retry_exc.retryable:
                    self._breaker.record_failure()
                if not retry_exc.retryable:
                    raise
                fallback = self._fallback_for(provider)
                if fallback is None:
                    raise
                logger.warning(
                    "Provider %s did not respond; switching to %s",
                    provider.name,
                    fallback.name,
                )
                fallback_request = request.model_copy(update={"model": None})
                return await self._budgeted_call(
                    fallback,
                    fallback_request,
                    budget=budget,
                    token_usage=token_usage,
                    call_type=call_type,
                    round=round,
                    retry=False,
                    fallback=True,
                )

    async def _budgeted_call(
        self,
        provider: Any,
        request: GenerationRequest,
        *,
        budget: RequestBudget | None,
        token_usage: RequestTokenUsage | None,
        call_type: str,
        round: int,
        retry: bool,
        fallback: bool,
    ) -> GenerationResponse:
        if budget is not None:
            budget.begin_model_call(allow_synthesis=(call_type == "synthesize"))
        response = await self._call(provider, request, retry=retry, fallback=fallback)
        if budget is not None:
            budget.record_tokens(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        if token_usage is not None:
            entry = token_usage.record(
                model=response.model or (request.model or ""),
                call_type=call_type,
                round=round,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                provider=provider.name,
                retry=retry,
                fallback=fallback,
            )
            if self._metrics is not None:
                self._metrics.record_token_usage(
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    usage_source=entry.usage_source,
                )
        self._breaker.record_success()
        return response

    async def _call(
        self,
        provider: Any,
        request: GenerationRequest,
        *,
        retry: bool = False,
        fallback: bool = False,
    ) -> GenerationResponse:
        started = time.perf_counter()
        # Routine attempts show up in chat.request metrics; only surface
        # retries/fallbacks as first-class INFO events.
        attempt_level = logging.INFO if retry or fallback else logging.DEBUG
        emit_event(
            MODEL_ATTEMPT,
            level=attempt_level,
            provider=provider.name,
            retry=retry,
            fallback=fallback,
        )
        with trace_llm_call(
            model=request.model or getattr(provider, "_default_model", ""),
            provider=provider.name,
            temperature=request.temperature,
        ) as span:
            span.set_attribute("llm.retry", retry)
            span.set_attribute("llm.fallback", fallback)
            try:
                response = await provider.generate(request)
                if response.input_tokens is not None:
                    span.set_attribute("llm.token_count.prompt", response.input_tokens)
                if response.output_tokens is not None:
                    span.set_attribute(
                        "llm.token_count.completion", response.output_tokens
                    )
                total = getattr(response, "total_tokens", None)
                if (
                    total is None
                    and response.input_tokens is not None
                    and response.output_tokens is not None
                ):
                    total = response.input_tokens + response.output_tokens
                if total is not None:
                    span.set_attribute("llm.token_count.total", total)
                finish_reason = getattr(response, "finish_reason", None)
                if finish_reason:
                    span.set_attribute("llm.finish_reason", str(finish_reason))
            except Exception:
                self._record(started, error=True, retry=retry, fallback=fallback)
                raise
            self._record(started, error=False, retry=retry, fallback=fallback)
            return response

    async def _resolve(self) -> tuple[Any, str | None]:
        """Admin pin wins. Otherwise use AI_ACTIVE_PROVIDER (OpenAI by
        default). Cheaper Inference is the cross-fallback only."""
        if self._selection_store is not None:
            selection = await self._selection_store.get()
            if selection is not None:
                provider = self._model_router.get(selection.provider)
                if provider is not None:
                    return provider, selection.model
                logger.warning(
                    "Selected provider '%s' is not registered; using active provider",
                    selection.provider,
                )

        active = self._model_router.get_active()
        if active is not None:
            return active, None
        preferred = self._model_router.get(OPENAI_PROVIDER_NAME)
        if preferred is not None:
            return preferred, None
        return self._model_router.get(CHEAPER_PROVIDER_NAME), None

    def _fallback_for(self, provider: Any) -> Any | None:
        fallback_name = _FALLBACK_PROVIDER.get(provider.name)
        if fallback_name is None:
            return None
        fallback = self._model_router.get(fallback_name)
        if fallback is None or fallback.name == provider.name:
            return None
        return fallback

    def _record(
        self,
        started: float,
        *,
        error: bool,
        retry: bool = False,
        fallback: bool = False,
    ) -> None:
        if self._metrics is None:
            return
        self._metrics.record_provider_call(
            (time.perf_counter() - started) * 1000,
            error=error,
            retry=retry,
            fallback=fallback,
        )
