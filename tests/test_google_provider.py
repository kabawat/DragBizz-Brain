from app.providers.openai_compatible import (
    _parse_completion,
    _to_openai_message,
)
from app.schemas.chat import ChatMessage


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
