from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.executors.tool_executor import ToolExecutor
from app.guards.output_guard import OutputGuard
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.prompts.fallback import get_fallback_message
from app.providers.base import ModelProvider
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolResult
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"

guard = OutputGuard()


def _result(data: dict[str, Any]) -> ToolResult:
    return ToolResult(tool="today_sale", success=True, data=data)


# ---------------------------------------------------------------- secrets


@pytest.mark.parametrize(
    "text",
    [
        "Your key is sk-abc123def456ghi789jkl.",
        "Use token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.c2lnbmF0dXJlLXBhcnQ",
        "Header: Bearer abcdef1234567890abcdef",
        "AWS: AKIAIOSFODNN7EXAMPLE",
        "Connect to mongodb://admin:pass@db.internal:27017/prod",
        'Set password="SuperSecret9" in settings.',
        "api_key: 9f8e7d6c5b4a3210",
    ],
)
def test_secret_patterns_are_caught_and_redacted(text: str) -> None:
    decision = guard.evaluate(text, [])
    assert decision.allowed is False
    assert decision.category == "SECRET_LEAK"
    assert decision.matched is not None
    assert "[REDACTED]" in decision.sanitized_text
    assert decision.matched not in decision.sanitized_text


def test_secret_redaction_keeps_surrounding_text() -> None:
    decision = guard.evaluate(
        "Aaj ki sale ₹1200 hai. Key: sk-abc123def456ghi789jkl. Dhanyavaad!",
        [_result({"revenue": 1200})],
    )
    assert decision.sanitized_text.startswith("Aaj ki sale ₹1200 hai.")
    assert decision.sanitized_text.endswith("Dhanyavaad!")


# ------------------------------------------------------- unsupported numbers


def test_currency_amount_backed_by_tool_result_passes() -> None:
    decision = guard.evaluate(
        "Aaj ki sale ₹1,200 hai aur profit Rs. 300.",
        [_result({"revenue": 1200, "profit": 300})],
    )
    assert decision.allowed is True


def test_currency_amount_without_tool_results_is_flagged() -> None:
    decision = guard.evaluate("Aaj ki sale ₹5000 hui.", [])
    assert decision.allowed is False
    assert decision.category == "UNSUPPORTED_NUMBERS"
    assert "5000" in (decision.matched or "")


def test_currency_amount_not_in_tool_results_is_flagged() -> None:
    decision = guard.evaluate(
        "Aaj ki sale ₹9999 hai.", [_result({"revenue": 1200})]
    )
    assert decision.allowed is False
    assert decision.category == "UNSUPPORTED_NUMBERS"


def test_decimal_and_comma_formats_normalize() -> None:
    decision = guard.evaluate(
        "Total Rs. 1,200.50 aaya.", [_result({"revenue": 1200.5})]
    )
    assert decision.allowed is True


def test_plain_numbers_without_currency_are_not_flagged() -> None:
    # Steps, quantities, form names — no currency marker, no flag.
    decision = guard.evaluate(
        "Step 2 mein GSTR-1 select karein, phir 3 items add karein.", []
    )
    assert decision.allowed is True


def test_clean_how_to_answer_passes_untouched() -> None:
    text = "POS kholen, product scan karein, aur Save Bill dabayen."
    decision = guard.evaluate(text, [])
    assert decision.allowed is True
    assert decision.sanitized_text == text


# ------------------------------------------------------------ chat wiring


class _StaticProvider(ModelProvider):
    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def name(self) -> str:
        return "static"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider="static", model="m", content=self._content, tool_calls=[]
        )


def _service(content: str, mode: str) -> ChatService:
    provider = _StaticProvider(content)
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = ToolRegistry()
    return ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test", output_guard_mode=mode),
        tool_executor=ToolExecutor(registry=registry, retailer=MagicMock()),
    )


def _handle(service: ChatService) -> str:
    response = asyncio.run(
        service.handle(
            ChatRequest(
                text="aaj ki sale?",
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
    return response.message


def test_enforce_mode_scrubs_secret_but_keeps_answer() -> None:
    message = _handle(
        _service("Key hai sk-abc123def456ghi789jkl, sambhal ke.", "enforce")
    )
    assert "sk-abc123def456ghi789jkl" not in message
    assert "[REDACTED]" in message
    assert "sambhal ke" in message


def test_enforce_mode_replaces_invented_numbers_with_fallback() -> None:
    message = _handle(_service("Aaj ki sale ₹5000 hui.", "enforce"))
    assert message == get_fallback_message("hi-IN")


def test_log_mode_flags_but_returns_original(
    caplog: pytest.LogCaptureFixture,
) -> None:
    content = "Aaj ki sale ₹5000 hui."
    with caplog.at_level(logging.WARNING):
        message = _handle(_service(content, "log"))
    assert message == content
    assert any(
        "Output guard flagged response" in record.message
        and "UNSUPPORTED_NUMBERS" in record.getMessage()
        for record in caplog.records
    )
    # Full response text must never be logged.
    assert all(content not in record.getMessage() for record in caplog.records)


def test_off_mode_skips_evaluation() -> None:
    content = "Key: sk-abc123def456ghi789jkl"
    assert _handle(_service(content, "off")) == content


def test_clean_response_passes_in_enforce_mode() -> None:
    content = "POS kholen aur bill banayen."
    assert _handle(_service(content, "enforce")) == content


# ------------------------------------------------------------ fallback copy


def test_fallback_message_language_fallback() -> None:
    assert get_fallback_message("en-US") != get_fallback_message("hi-IN")
    assert get_fallback_message("gu") != get_fallback_message("hi")
    # Unknown language falls back to Hindi.
    assert get_fallback_message("fr-FR") == get_fallback_message("hi-IN")
