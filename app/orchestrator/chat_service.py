from __future__ import annotations

from typing import Any

from app.config import Settings
from app.core.exceptions import AppError
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.prompts.system.chat import build_chat_system_prompt
from app.schemas.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    GenerationRequest,
    GenerationResponse,
)
from app.schemas.tool import ToolDefinition
from app.tools.registry import ToolRegistry


class ChatService:
    def __init__(
        self,
        *,
        gateway: AiGateway,
        tool_registry: ToolRegistry,
        settings: Settings,
        validator: ToolCallValidator | None = None,
    ) -> None:
        self._gateway = gateway
        self._registry = tool_registry
        self._settings = settings
        self._validator = validator or ToolCallValidator(tool_registry)

    async def handle(
        self,
        body: ChatRequest,
        *,
        user: dict[str, Any],
        request_id: str,
        store_id: str,
    ) -> ChatResponse:
        tools = list(self._registry.definitions())
        messages = [
            ChatMessage(
                role="system",
                content=build_chat_system_prompt(
                    language=body.language,
                    store_id=store_id,
                    tools=tools,
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

        return ChatResponse(
            message=generation.content or "",
            session_id=body.session_id,
            request_id=request_id,
            user_id=str(user["sub"]),
            provider=generation.provider,
            model=generation.model,
            tool_calls=tool_calls,
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
