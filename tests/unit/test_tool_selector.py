"""Unit tests for turn intent + dynamic tool loading."""

from __future__ import annotations

import json
from pathlib import Path

from app.orchestrator.tool_selector import (
    resolve_turn_intent,
    select_tools_for_question,
    should_retrieve_docs,
)
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)

ALL_NAMES = frozenset(
    definition.name
    for definition in (
        *READ_TOOL_DEFINITIONS,
        *WRITE_TOOL_DEFINITIONS,
        *SENSITIVE_TOOL_DEFINITIONS,
    )
)

_CASES_PATH = Path(__file__).parent.parent / "eval" / "routing_cases.json"
_CASES = json.loads(_CASES_PATH.read_text())["cases"]


def test_routing_cases_match_resolve_turn_intent() -> None:
    for case in _CASES:
        intent = resolve_turn_intent(case["question"], available=ALL_NAMES)
        assert intent.routing == case["expected_routing"], case["id"]
        if case["expected_routing"] in {"docs", "neither"}:
            assert intent.tool_names == frozenset(), case["id"]
        else:
            assert set(case["expected_tools"]) <= intent.tool_names, case["id"]
            assert intent.tool_names < ALL_NAMES, case["id"]


def test_docs_and_neither_offer_no_tools() -> None:
    for case in _CASES:
        if case["expected_routing"] not in {"docs", "neither"}:
            continue
        selected = select_tools_for_question(
            case["question"], available=ALL_NAMES
        )
        assert selected == frozenset(), case["id"]


def test_tools_and_both_include_expected_tools() -> None:
    for case in _CASES:
        if case["expected_routing"] not in {"tools", "both"}:
            continue
        selected = select_tools_for_question(
            case["question"], available=ALL_NAMES
        )
        assert set(case["expected_tools"]) <= selected, case["id"]
        assert selected < ALL_NAMES, case["id"]


def test_invoice_action_offers_invoice_subset() -> None:
    for question in (
        "Ramesh ke liye atta ka bill banao",
        "Make a bill",
    ):
        selected = select_tools_for_question(question, available=ALL_NAMES)
        assert "create_invoice_draft" in selected, question
        assert "search_customer" in selected, question
        assert "search_product" in selected, question
        assert "today_sale" not in selected, question
        assert selected < ALL_NAMES, question


def test_customer_action_offers_customer_subset() -> None:
    selected = select_tools_for_question(
        "naya customer banao",
        available=ALL_NAMES,
    )
    assert "create_customer" in selected
    assert "search_customer" in selected
    assert "create_invoice_draft" not in selected


def test_unknown_fails_open_to_all_available() -> None:
    intent = resolve_turn_intent("Namaste, madad chahiye", available=ALL_NAMES)
    assert intent.routing == "unknown"
    assert intent.tool_names == ALL_NAMES


def test_available_filters_unregistered_names() -> None:
    selected = select_tools_for_question(
        "aaj ki sale kitni hui?",
        available={"today_sale"},
    )
    assert selected == frozenset({"today_sale"})


def test_empty_available_returns_empty() -> None:
    assert select_tools_for_question("aaj ki sale", available=set()) == frozenset()


def test_should_retrieve_docs_by_routing() -> None:
    assert should_retrieve_docs("docs") is True
    assert should_retrieve_docs("both") is True
    assert should_retrieve_docs("unknown") is True
    assert should_retrieve_docs("tools") is False
    assert should_retrieve_docs("neither") is False
