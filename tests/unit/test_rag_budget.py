"""Unit tests for action vs how-to RAG documentation budget."""

from app.orchestrator.rag_budget import rag_docs_budget_for_question

FULL = 2000
ACTION = 512


def test_howto_keeps_full_budget() -> None:
    assert (
        rag_docs_budget_for_question(
            "POS se bill kaise banau?",
            full_budget=FULL,
            action_budget=ACTION,
        )
        == FULL
    )


def test_action_bill_uses_action_budget() -> None:
    assert (
        rag_docs_budget_for_question(
            "Ramesh ke liye atta ka bill banao",
            full_budget=FULL,
            action_budget=ACTION,
        )
        == ACTION
    )


def test_live_sale_uses_action_budget() -> None:
    assert (
        rag_docs_budget_for_question(
            "aaj ki sale kitni hui?",
            full_budget=FULL,
            action_budget=ACTION,
        )
        == ACTION
    )


def test_howto_wins_when_both_match() -> None:
    assert (
        rag_docs_budget_for_question(
            "invoice kaise banao steps batao",
            full_budget=FULL,
            action_budget=ACTION,
        )
        == FULL
    )


def test_unknown_defaults_to_full_budget() -> None:
    assert (
        rag_docs_budget_for_question(
            "Namaste, madad chahiye",
            full_budget=FULL,
            action_budget=ACTION,
        )
        == FULL
    )


def test_action_budget_capped_by_full() -> None:
    assert (
        rag_docs_budget_for_question(
            "bill banao",
            full_budget=400,
            action_budget=512,
        )
        == 400
    )
