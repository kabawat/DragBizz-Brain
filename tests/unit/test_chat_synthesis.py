"""A1 — second LLM synthesis turn after tool execution."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.prompts.fallback import get_fallback_message
from app.providers.base import ModelProvider
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolResult
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"


class CapturingProvider(ModelProvider):
    def __init__(self, responses: list[GenerationResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "capturing"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register(definition, READ_TOOL_HANDLERS[definition.name])
    return registry


def _service(
    provider: ModelProvider,
    *,
    settings: Settings | None = None,
    tool_results: list[ToolResult] | None = None,
) -> ChatService:
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = _registry()

    executor = MagicMock(spec=ToolExecutor)
    executor.execute_reads = AsyncMock(
        return_value=tool_results
        if tool_results is not None
        else [
            ToolResult(
                tool="today_sale",
                success=True,
                data={"revenue": 500, "profit": 100, "sales": 3},
            )
        ]
    )

    return ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=settings
        or Settings(
            environment="test",
            output_guard_mode="enforce",
            chat_synthesis_max_tokens=256,
        ),
        tool_executor=executor,
    )


def _handle(service: ChatService) -> Any:
    return asyncio.run(
        service.handle(
            ChatRequest(
                text="Aaj ki sale kitni hai?",
                sessionId="s1",
                storeId=STORE_ID,
                language="hi-IN",
            ),
            user={"sub": "u1"},
            request_id="r1",
            store_id=STORE_ID,
            access_token="token",
        )
    )


def test_synthesis_message_uses_tool_amounts() -> None:
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Fetching.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="today_sale",
                        arguments={"storeId": STORE_ID},
                    )
                ],
                input_tokens=40,
                output_tokens=10,
            ),
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Aaj ki sale ₹500 hai, profit ₹100.",
                input_tokens=80,
                output_tokens=20,
            ),
        ]
    )
    response = _handle(_service(provider))

    assert response.message == "Aaj ki sale ₹500 hai, profit ₹100."
    assert response.tool_results[0].data["revenue"] == 500
    assert len(provider.requests) == 2

    synthesis = provider.requests[1]
    assert synthesis.tools is None
    assert synthesis.tool_choice == "none"
    assert synthesis.max_tokens == 256
    assert any(m.role == "tool" for m in synthesis.messages)
    tool_msg = next(m for m in synthesis.messages if m.role == "tool")
    assert tool_msg.tool_call_id == "call_1"
    payload = json.loads(tool_msg.content)
    assert payload["success"] is True
    assert payload["data"]["revenue"] == 500


def test_synthesis_skipped_when_no_tool_calls() -> None:
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing",
                model="m",
                content="POS kholen aur bill banayen.",
            )
        ]
    )
    registry = _registry()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    service = ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test", output_guard_mode="enforce"),
        tool_executor=ToolExecutor(registry=registry, retailer=MagicMock()),
    )
    response = _handle(service)

    assert response.message == "POS kholen aur bill banayen."
    assert len(provider.requests) == 1
    assert provider.requests[0].tool_choice == "auto"


def test_invented_synthesis_amount_blocked_by_output_guard() -> None:
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Fetching.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="today_sale",
                        arguments={"storeId": STORE_ID},
                    )
                ],
            ),
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Aaj ki sale ₹9999 hai.",
            ),
        ]
    )
    response = _handle(_service(provider))
    assert response.message == get_fallback_message("hi-IN")


def test_grounded_synthesis_passes_output_guard() -> None:
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Fetching.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="today_sale",
                        arguments={"storeId": STORE_ID},
                    )
                ],
            ),
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Aaj ki sale ₹500 hai.",
            ),
        ]
    )
    response = _handle(
        _service(
            provider,
            settings=Settings(
                environment="test",
                output_guard_mode="enforce",
                chat_synthesis_max_tokens=256,
            ),
        )
    )
    assert response.message == "Aaj ki sale ₹500 hai."
