"""Intent-based system prompt assembly + compression checks."""

from __future__ import annotations

from app.prompts.system.chat import build_chat_system_prompt
from app.rag.chunker import estimate_tokens
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)

STORE_ID = "507f1f77bcf86cd799439011"

_BY_NAME = {
    definition.name: definition
    for definition in (
        *READ_TOOL_DEFINITIONS,
        *WRITE_TOOL_DEFINITIONS,
        *SENSITIVE_TOOL_DEFINITIONS,
    )
}


def _tools(*names: str):
    return [_BY_NAME[name] for name in names]


def test_neither_prompt_is_minimal() -> None:
    prompt = build_chat_system_prompt(
        language="en",
        store_id=STORE_ID,
        tools=[],
        documentation="",
        routing="neither",
    )
    assert "You may only call these tools" not in prompt
    assert "create_invoice_draft" not in prompt
    assert "Never invent, guess, or 'pick for them'" not in prompt
    assert "one short warm line" in prompt


def test_docs_prompt_omits_write_and_invoice_rules() -> None:
    prompt = build_chat_system_prompt(
        language="hi",
        store_id=STORE_ID,
        tools=[],
        documentation="[1] source=invoice-pos.md\nPOS steps.",
        routing="docs",
    )
    assert "You may only call these tools" not in prompt
    assert "Never invent, guess, or 'pick for them'" not in prompt
    assert "create_invoice_draft MUST" not in prompt
    assert "Never answer live numbers from Documentation" in prompt
    assert "Documentation:\n[1] source=invoice-pos.md" in prompt
    assert "must come from tool calls only" not in prompt


def test_tools_sale_prompt_has_grounding_without_invoice_chain() -> None:
    prompt = build_chat_system_prompt(
        language="hi",
        store_id=STORE_ID,
        tools=_tools("today_sale"),
        documentation="",
        routing="tools",
    )
    assert "You may only call these tools: today_sale." in prompt
    assert "must come from tool calls only" in prompt
    assert "create_invoice_draft MUST" not in prompt
    assert "Never invent, guess, or 'pick for them'" not in prompt
    assert "Documentation:" not in prompt


def test_invoice_tools_include_write_sensitive_and_chain_rules() -> None:
    prompt = build_chat_system_prompt(
        language="hi",
        store_id=STORE_ID,
        tools=_tools(
            "search_customer",
            "search_product",
            "create_customer",
            "create_invoice_draft",
            "update_invoice_draft",
            "release_invoice",
        ),
        documentation="",
        routing="tools",
    )
    assert "Never invent, guess, or 'pick for them'" in prompt
    assert "do NOT call the write tool" in prompt
    assert "openPath" in prompt
    assert "create_invoice_draft MUST" in prompt
    assert "Sensitive tools (release_invoice)" in prompt
    assert "shall I proceed" in prompt


def test_both_prompt_keeps_tools_and_docs_rules() -> None:
    prompt = build_chat_system_prompt(
        language="hi",
        store_id=STORE_ID,
        tools=_tools("today_sale"),
        documentation="[1] source=reports-sales.md\nDownload steps.",
        routing="both",
    )
    assert "must come from tool calls only" in prompt
    assert "call the tool for the numbers" in prompt
    assert "Documentation:\n[1] source=reports-sales.md" in prompt


def test_compressed_invoice_prompt_stays_under_token_budget() -> None:
    """Full invoice ruleset should stay lean after prompt compression."""
    prompt = build_chat_system_prompt(
        language="hi",
        store_id=STORE_ID,
        tools=_tools(
            "search_customer",
            "search_product",
            "create_customer",
            "create_invoice_draft",
            "update_invoice_draft",
            "release_invoice",
        ),
        documentation="",
        routing="tools",
    )
    assert estimate_tokens(prompt) <= 900
