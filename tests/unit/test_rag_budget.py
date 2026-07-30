"""Unit tests for routing-based RAG documentation budget."""

from app.orchestrator.rag_budget import rag_docs_budget_for_routing

FAQ = 1000
ACTION = 512


def test_docs_routing_uses_faq_budget() -> None:
    assert (
        rag_docs_budget_for_routing(
            "docs", faq_budget=FAQ, action_budget=ACTION
        )
        == FAQ
    )


def test_both_routing_uses_faq_budget() -> None:
    assert (
        rag_docs_budget_for_routing(
            "both", faq_budget=FAQ, action_budget=ACTION
        )
        == FAQ
    )


def test_unknown_routing_uses_faq_budget() -> None:
    assert (
        rag_docs_budget_for_routing(
            "unknown", faq_budget=FAQ, action_budget=ACTION
        )
        == FAQ
    )


def test_tools_routing_uses_action_budget() -> None:
    assert (
        rag_docs_budget_for_routing(
            "tools", faq_budget=FAQ, action_budget=ACTION
        )
        == ACTION
    )


def test_action_budget_capped_by_faq() -> None:
    assert (
        rag_docs_budget_for_routing(
            "tools", faq_budget=400, action_budget=512
        )
        == 400
    )
