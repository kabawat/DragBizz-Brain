"""Per-component prompt token breakdown."""

from app.orchestrator.prompt_tokens import estimate_prompt_token_breakdown
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolDefinition, ToolRisk


def test_breakdown_separates_system_tools_rag_history_user() -> None:
    tools = [
        ToolDefinition(
            name="today_sale",
            description="Today sales.",
            risk=ToolRisk.READ,
            parameters={
                "type": "object",
                "properties": {"storeId": {"type": "string"}},
                "required": ["storeId"],
            },
        )
    ]
    docs = "[1] source=a.md\n" + ("step " * 40)
    system = "You are helpful.\nRules:\n- be brief.\n\nDocumentation:\n" + docs
    breakdown = estimate_prompt_token_breakdown(
        system_content=system,
        documentation=docs,
        tools=tools,
        history_messages=[
            ChatMessage(role="user", content="earlier question"),
            ChatMessage(role="assistant", content="earlier answer"),
        ],
        user_text="POS kaise banau?",
    )
    assert breakdown.system > 0
    assert breakdown.tools > 0
    assert breakdown.rag > 0
    assert breakdown.history > 0
    assert breakdown.user > 0
    assert breakdown.system < len(system)  # not counting full string as chars
    metrics = breakdown.as_metrics()
    assert metrics["prompt_rag_tokens"] == breakdown.rag
    assert metrics["prompt_tools_tokens"] == breakdown.tools


def test_empty_tools_and_docs_are_zero() -> None:
    breakdown = estimate_prompt_token_breakdown(
        system_content="Short system.",
        documentation="",
        tools=[],
        history_messages=[],
        user_text="hi",
    )
    assert breakdown.tools == 0
    assert breakdown.rag == 0
    assert breakdown.history == 0
    assert breakdown.user > 0
