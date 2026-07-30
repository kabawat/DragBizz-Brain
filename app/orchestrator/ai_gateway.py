from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.exceptions import AppError
from app.observability.metrics import MetricsRegistry
from app.orchestrator.model_config import ModelSelectionStore
from app.orchestrator.model_router import ModelRouter
from app.prompts.synthesis import (
    build_continuation_instruction,
    build_synthesis_instruction,
)
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

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

        started = time.perf_counter()
        try:
            response = await provider.generate(request)
        except Exception:
            self._record(started, error=True)
            raise
        self._record(started, error=False)
        return response

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

    async def _resolve(self) -> tuple[Any, str | None]:
        """Admin selection wins when its provider is registered; otherwise
        fall back to the env-configured active provider and default model."""
        if self._selection_store is not None:
            selection = await self._selection_store.get()
            if selection is not None:
                provider = self._model_router.get(selection.provider)
                if provider is not None:
                    return provider, selection.model
                logger.warning(
                    "Selected provider '%s' is not registered; "
                    "falling back to active provider",
                    selection.provider,
                )
        return self._model_router.get_active(), None

    def _record(self, started: float, *, error: bool) -> None:
        if self._metrics is None:
            return
        self._metrics.record_provider_call(
            (time.perf_counter() - started) * 1000, error=error
        )
