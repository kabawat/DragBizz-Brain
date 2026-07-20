from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.schemas.chat import ChatMessage, GenerationRequest
from app.schemas.tool import ToolDefinition, ToolRisk


def _settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "environment": "test",
        "openai_api_key": "test-key",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "gpt-4o-mini",
        "provider_timeout_seconds": 5.0,
    }
    data.update(overrides)
    return Settings(**data)


def test_openai_provider_normalizes_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "content": "Checking sales",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "today_sale",
                                        "arguments": (
                                            '{"storeId":'
                                            '"507f1f77bcf86cd799439011"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAICompatibleProvider(_settings(), client)
            result = await provider.generate(
                GenerationRequest(
                    messages=[ChatMessage(role="user", content="sale?")],
                    tools=[
                        ToolDefinition(
                            name="today_sale",
                            description="sales",
                            risk=ToolRisk.READ,
                            parameters={
                                "type": "object",
                                "properties": {"storeId": {"type": "string"}},
                            },
                        )
                    ],
                )
            )

        assert result.provider == "openai_compatible"
        assert result.content == "Checking sales"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "today_sale"
        assert result.tool_calls[0].arguments == {
            "storeId": "507f1f77bcf86cd799439011"
        }

    asyncio.run(run())


def test_openai_provider_maps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAICompatibleProvider(_settings(), client)
            with pytest.raises(AppError) as exc_info:
                await provider.generate(
                    GenerationRequest(
                        messages=[ChatMessage(role="user", content="hi")]
                    )
                )
        assert exc_info.value.code == "AI_PROVIDER_ERROR"
        assert exc_info.value.status_code == 502

    asyncio.run(run())


def test_openai_provider_requires_api_key() -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            provider = OpenAICompatibleProvider(
                _settings(openai_api_key=None), client
            )
            with pytest.raises(AppError) as exc_info:
                await provider.generate(
                    GenerationRequest(
                        messages=[ChatMessage(role="user", content="hi")]
                    )
                )
        assert exc_info.value.code == "AI_PROVIDER_NOT_CONFIGURED"

    asyncio.run(run())


def test_openai_provider_rejects_malformed_tool_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "today_sale",
                                        "arguments": "{not-json",
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAICompatibleProvider(_settings(), client)
            with pytest.raises(AppError) as exc_info:
                await provider.generate(
                    GenerationRequest(
                        messages=[ChatMessage(role="user", content="hi")]
                    )
                )
        assert exc_info.value.code == "TOOL_ARGS_INVALID"

    asyncio.run(run())
