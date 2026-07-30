"""Unit tests for AiGateway chat turn / repair / synthesis helpers."""

from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import AppError
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition, ToolRisk


class RecordingProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []
        self._responses: list[GenerationResponse] = []
        self._raise: AppError | None = None

    @property
    def name(self) -> str:
        return "fake"

    def enqueue(self, response: GenerationResponse) -> None:
        self._responses.append(response)

    def fail_once(self, exc: AppError) -> None:
        self._raise = exc

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        if self._raise is not None:
            exc = self._raise
            self._raise = None
            raise exc
        if not self._responses:
            return GenerationResponse(
                provider=self.name, model="m", content="ok"
            )
        return self._responses.pop(0)


TOOLS = [
    ToolDefinition(
        name="today_sale",
        description="Today sale",
        risk=ToolRisk.READ,
        parameters={
            "type": "object",
            "properties": {"storeId": {"type": "string"}},
            "required": ["storeId"],
        },
    )
]


def _gateway() -> tuple[AiGateway, RecordingProvider]:
    provider = RecordingProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    return AiGateway(router), provider


def test_generate_chat_turn_sets_tools_auto() -> None:
    gateway, provider = _gateway()
    asyncio.run(
        gateway.generate_chat_turn(
            [ChatMessage(role="user", content="hi")],
            TOOLS,
            temperature=0.2,
            max_tokens=100,
        )
    )
    assert provider.requests[-1].tool_choice == "auto"
    assert provider.requests[-1].tools == TOOLS


def test_continue_or_synthesize_disables_tools_when_final() -> None:
    gateway, provider = _gateway()
    asyncio.run(
        gateway.continue_or_synthesize(
            [ChatMessage(role="user", content="hi")],
            TOOLS,
            language="en",
            allow_tools=False,
            temperature=0.2,
            max_tokens=200,
        )
    )
    req = provider.requests[-1]
    assert req.tool_choice == "none"
    assert req.tools is None
    assert req.messages[-1].role == "user"
    assert req.messages[-1].content


def test_generate_with_optional_parse_repair_retries() -> None:
    gateway, provider = _gateway()
    provider.fail_once(
        AppError(
            code="TOOL_ARGS_INVALID",
            message="bad args",
            status_code=400,
        )
    )
    provider.enqueue(
        GenerationResponse(provider="fake", model="m", content="fixed")
    )

    response = asyncio.run(
        gateway.generate_with_optional_parse_repair(
            [ChatMessage(role="user", content="hi")],
            TOOLS,
            store_id="store1",
            temperature=0.1,
            max_tokens=50,
            describe_errors=lambda _calls, _sid: ["today_sale: bad"],
        )
    )
    assert response.content == "fixed"
    assert len(provider.requests) == 2
    assert "validation failed" in (provider.requests[-1].messages[-1].content or "")


def test_repair_tool_calls_uses_describe_errors_when_no_detail() -> None:
    gateway, provider = _gateway()
    previous = GenerationResponse(
        provider="fake",
        model="m",
        content="",
        tool_calls=[
            ToolCall(id="1", name="today_sale", arguments={}),
        ],
    )
    asyncio.run(
        gateway.repair_tool_calls(
            messages=[ChatMessage(role="user", content="hi")],
            tools=TOOLS,
            previous=previous,
            store_id="store1",
            temperature=0.1,
            max_tokens=50,
            describe_errors=lambda _calls, _sid: ["today_sale: missing storeId"],
        )
    )
    detail_msg = provider.requests[-1].messages[-1].content or ""
    assert "missing storeId" in detail_msg
    assert "storeId=store1" in detail_msg


def test_generate_with_optional_parse_repair_rethrows_other_errors() -> None:
    gateway, provider = _gateway()
    provider.fail_once(
        AppError(code="PROVIDER_ERROR", message="boom", status_code=502)
    )
    with pytest.raises(AppError) as exc_info:
        asyncio.run(
            gateway.generate_with_optional_parse_repair(
                [ChatMessage(role="user", content="hi")],
                TOOLS,
                store_id="store1",
                temperature=0.1,
                max_tokens=50,
                describe_errors=lambda _c, _s: [],
            )
        )
    assert exc_info.value.code == "PROVIDER_ERROR"
