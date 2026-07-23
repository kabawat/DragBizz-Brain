from __future__ import annotations

import logging
import time
from typing import Any

from app.config import Settings
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.prompts.fallback import get_fallback_message
from app.prompts.refusal import get_refusal_message
from app.prompts.system.chat import (
    build_chat_system_prompt,
    build_documentation_block,
)
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    GenerationRequest,
    GenerationResponse,
)
from app.schemas.tool import ToolDefinition
from app.tools.registry import ToolRegistry

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
    ) -> None:
        self._gateway = gateway
        self._registry = tool_registry
        self._settings = settings
        self._executor = tool_executor
        self._validator = validator or ToolCallValidator(tool_registry)
        self._retriever = retriever
        self._input_guard = input_guard or InputGuard()
        self._output_guard = output_guard or OutputGuard()

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
        refusal = self._guard_input(body)
        if refusal is not None:
            return ChatResponse(
                message=refusal,
                session_id=body.session_id,
                request_id=request_id,
                user_id=str(user["sub"]),
                provider="input_guard",
                model="",
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
            ChatMessage(role="user", content=body.text),
        ]

        generation = await self._generate_with_optional_parse_repair(
            messages, tools, store_id=store_id
        )
        try:
            tool_calls = self._validator.validate(
                generation.tool_calls, store_id=store_id
            )
        except AppError as exc:
            if exc.code not in {"TOOL_ARGS_INVALID", "TOOL_NOT_ALLOWED"}:
                raise
            generation = await self._repair(
                messages=messages,
                tools=tools,
                previous=generation,
                store_id=store_id,
                detail=exc.message,
            )
            tool_calls = self._validator.validate(
                generation.tool_calls, store_id=store_id
            )

        tool_results = await self._executor.execute_reads(
            tool_calls,
            access_token=access_token,
            store_id=store_id,
        )

        message = self._guard_output(
            generation.content or "",
            tool_results=tool_results,
            language=body.language,
        )

        self._log_request_metrics(
            request_id=request_id,
            generation=generation,
            retrieved=retrieved,
            tool_calls=tool_calls,
            started=started,
        )

        return ChatResponse(
            message=message,
            session_id=body.session_id,
            request_id=request_id,
            user_id=str(user["sub"]),
            provider=generation.provider,
            model=generation.model,
            tool_calls=tool_calls,
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

    def _log_request_metrics(
        self,
        *,
        request_id: str,
        generation: GenerationResponse,
        retrieved: list[RetrievedChunk],
        tool_calls: list[Any],
        started: float,
    ) -> None:
        # Doc IDs/scores, tokens, latency, cost — never question or answer
        # text, never user data (rule.md #19).
        cost_usd: float | None = None
        if generation.input_tokens is not None and generation.output_tokens is not None:
            cost_usd = round(
                generation.input_tokens
                * self._settings.chat_input_usd_per_million_tokens
                / 1_000_000
                + generation.output_tokens
                * self._settings.chat_output_usd_per_million_tokens
                / 1_000_000,
                8,
            )
        logger.info(
            "Chat request metrics",
            extra={
                "request_id": request_id,
                "metrics": {
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "provider": generation.provider,
                    "model": generation.model,
                    "input_tokens": generation.input_tokens,
                    "output_tokens": generation.output_tokens,
                    "est_cost_usd": cost_usd,
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
