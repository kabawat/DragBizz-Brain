from __future__ import annotations

import json
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
from app.prompts.synthesis import build_synthesis_instruction
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
from app.schemas.tool import ToolCall, ToolDefinition, ToolResult
from app.sessions import (
    InMemorySessionStore,
    SessionStore,
    SessionTurn,
    turns_to_messages,
)
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
        session_store: SessionStore | None = None,
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

        synthesis: GenerationResponse | None = None
        if tool_calls:
            synthesis = await self._synthesize(
                messages=messages,
                tool_calls=tool_calls,
                tool_results=tool_results,
                language=body.language,
            )
            reply = synthesis.content
            reply_provider = synthesis.provider
            reply_model = synthesis.model
        else:
            reply = generation.content or ""
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

        self._log_request_metrics(
            request_id=request_id,
            generation=generation,
            synthesis=synthesis,
            retrieved=retrieved,
            tool_calls=tool_calls,
            history_turns=len(prior_turns),
            started=started,
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

    async def _synthesize(
        self,
        *,
        messages: list[ChatMessage],
        tool_calls: list[ToolCall],
        tool_results: list[ToolResult],
        language: str,
    ) -> GenerationResponse:
        synthesis_messages = list(messages)
        synthesis_messages.append(
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=tool_calls,
            )
        )
        for call, result in zip(tool_calls, tool_results, strict=True):
            synthesis_messages.append(
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
        synthesis_messages.append(
            ChatMessage(
                role="user",
                content=build_synthesis_instruction(language=language),
            )
        )
        return await self._gateway.generate(
            GenerationRequest(
                messages=synthesis_messages,
                temperature=self._settings.chat_temperature,
                max_tokens=self._settings.chat_synthesis_max_tokens,
                tools=None,
                tool_choice="none",
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

    def _log_request_metrics(
        self,
        *,
        request_id: str,
        generation: GenerationResponse,
        synthesis: GenerationResponse | None,
        retrieved: list[RetrievedChunk],
        tool_calls: list[Any],
        history_turns: int,
        started: float,
    ) -> None:
        # Doc IDs/scores, tokens, latency, cost — never question or answer
        # text, never user data (rule.md #19).
        input_tokens = _sum_optional_tokens(
            generation.input_tokens,
            synthesis.input_tokens if synthesis else None,
        )
        output_tokens = _sum_optional_tokens(
            generation.output_tokens,
            synthesis.output_tokens if synthesis else None,
        )
        cost_usd: float | None = None
        if input_tokens is not None and output_tokens is not None:
            cost_usd = round(
                input_tokens
                * self._settings.chat_input_usd_per_million_tokens
                / 1_000_000
                + output_tokens
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
                    "provider": (
                        synthesis.provider if synthesis else generation.provider
                    ),
                    "model": synthesis.model if synthesis else generation.model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "tool_turn_input_tokens": generation.input_tokens,
                    "tool_turn_output_tokens": generation.output_tokens,
                    "synthesis_input_tokens": (
                        synthesis.input_tokens if synthesis else None
                    ),
                    "synthesis_output_tokens": (
                        synthesis.output_tokens if synthesis else None
                    ),
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


def _sum_optional_tokens(*values: int | None) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)
