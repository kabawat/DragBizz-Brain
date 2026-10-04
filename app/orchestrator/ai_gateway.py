from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any

from app.core.exceptions import AppError
from app.observability.metrics import MetricsRegistry
from app.orchestrator.model_config import ModelSelectionStore
from app.orchestrator.model_router import ModelRouter
from app.prompts.synthesis import (
    build_continuation_instruction,
    build_synthesis_instruction,
)
from app.providers.openai_compatible import (
    CHEAPER_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
)
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

_FALLBACK_PROVIDER = {
    OPENAI_PROVIDER_NAME: CHEAPER_PROVIDER_NAME,
    CHEAPER_PROVIDER_NAME: OPENAI_PROVIDER_NAME,
}
_turn_routing: ContextVar[str | None] = ContextVar("ai_turn_routing", default=None)


def set_turn_routing(routing: str | None) -> Token[str | None]:
    return _turn_routing.set(routing)


def reset_turn_routing(token: Token[str | None]) -> None:
    _turn_routing.reset(token)

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
    ) -> None:
        self._model_router = model_router
        self._selection_store = selection_store
        self._metrics = metrics

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        provider, model = await self._resolve()
        if model is not None:
            request = request.model_copy(update={"model": model})

        try:
            return await self._call(provider, request)
        except AppError as exc:
            fallback = self._fallback_for(provider) if exc.retryable else None
            if fallback is None:
                raise
            logger.warning(
                "Provider %s did not respond; switching to %s",
                provider.name,
                fallback.name,
            )
            # Drop the primary model name so the fallback uses its own model.
            fallback_request = request.model_copy(update={"model": None})
            return await self._call(fallback, fallback_request)

    async def generate_chat_turn(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        temperature: float,
        max_tokens: int,
    ) -> GenerationResponse:
        return await self.generate(
            GenerationRequest(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools or None,
                tool_choice="auto" if tools else "none",
            )
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
    ) -> GenerationResponse:
        try:
            return await self.generate_chat_turn(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AppError as exc:
            if exc.code != "TOOL_ARGS_INVALID":
                raise
            return await self.repair_tool_calls(
                messages=messages,
                tools=tools,
                previous=None,
                store_id=store_id,
                detail=exc.message,
                temperature=temperature,
                max_tokens=max_tokens,
                describe_errors=describe_errors,
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
            )
        )

    async def _call(
        self, provider: Any, request: GenerationRequest
    ) -> GenerationResponse:
        started = time.perf_counter()
        try:
            response = await provider.generate(request)
        except Exception:
            self._record(started, error=True)
            raise
        self._record(started, error=False)
        return response

    async def _resolve(self) -> tuple[Any, str | None]:
        """Admin pin wins. Otherwise chat uses Cheaper Inference
        (deepseek-v4.1-flash). OpenAI is only the fallback."""
        if self._selection_store is not None:
            selection = await self._selection_store.get()
            if selection is not None:
                provider = self._model_router.get(selection.provider)
                if provider is not None:
                    return provider, selection.model
                logger.warning(
                    "Selected provider '%s' is not registered; "
                    "using task routing",
                    selection.provider,
                )

        preferred = self._model_router.get(CHEAPER_PROVIDER_NAME)
        if preferred is not None:
            return preferred, None
        return self._model_router.get_active(), None

    def _fallback_for(self, provider: Any) -> Any | None:
        fallback_name = _FALLBACK_PROVIDER.get(provider.name)
        if fallback_name is None:
            return None
        fallback = self._model_router.get(fallback_name)
        if fallback is None or fallback.name == provider.name:
            return None
        return fallback

    def _record(self, started: float, *, error: bool) -> None:
        if self._metrics is None:
            return
        self._metrics.record_provider_call(
            (time.perf_counter() - started) * 1000, error=error
        )
