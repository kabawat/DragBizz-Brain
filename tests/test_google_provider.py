import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.providers.openai_compatible import (
    OpenAICompatibleProvider,
    _parse_completion,
    _to_openai_message,
)
from app.schemas.chat import ChatMessage, GenerationRequest


def test_gemini_thought_signature_round_trips() -> None:
    signature = "sig-abc"
    parsed = _parse_completion(
        {
            "model": "gemini-3.1-flash-lite",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_today_sales",
                                    "arguments": "{}",
                                },
                                "extra_content": {
                                    "google": {"thought_signature": signature}
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        },
        provider_name="google_ai",
    )
    assert parsed.tool_calls[0].thought_signature == signature
    dumped = parsed.tool_calls[0].model_dump()
    assert "thought_signature" not in dumped

    echoed = _to_openai_message(
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=parsed.tool_calls,
        )
    )
    assert echoed["tool_calls"][0]["extra_content"]["google"][
        "thought_signature"
    ] == signature


def test_ssl_transport_failure_is_retryable() -> None:
    async def run() -> None:
        http_client = MagicMock()
        http_client.post = AsyncMock(side_effect=ssl.SSLError("bad record mac"))
        provider = OpenAICompatibleProvider(
            Settings(),
            http_client,
            api_key="test-key",
            base_url="https://example.test/v1",
        )
        request = GenerationRequest(messages=[ChatMessage(role="user", content="hi")])

        with pytest.raises(AppError) as raised:
            await provider.generate(request)

        assert raised.value.code == "AI_PROVIDER_ERROR"
        assert raised.value.retryable is True

    asyncio.run(run())
