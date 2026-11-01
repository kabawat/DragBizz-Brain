from __future__ import annotations

import pytest

from app.orchestrator.progress import (
    TOOL_PROGRESS_LABELS,
    get_parallel_tools_label,
    get_tool_progress_label,
)
from app.orchestrator.tool_discovery import TOOL_METADATA_CATALOG
from app.orchestrator.tool_selector import (
    is_pure_chitchat,
    resolve_turn_intent,
    user_requested_sensitive_action,
)


def test_all_catalog_tools_have_progress_labels():
    """Ensure every registered tool has a user-friendly, domain-safe progress label."""
    for tool_name in TOOL_METADATA_CATALOG:
        label = get_tool_progress_label(tool_name)
        assert label is not None
        assert len(label) > 5
        assert label.endswith("…")
        # Ensure raw technical names like underscore are not in the display label
        assert "_" not in label


def test_parallel_tools_label_coherence():
    """Test combined labels for parallel tool execution without flickering."""
    # Single tool
    assert get_parallel_tools_label(["today_sale"]) == "Fetching today's sales & revenue records…"

    # Same domain: sales
    sales_combined = get_parallel_tools_label(["today_sale", "list_invoices"])
    assert sales_combined == "Fetching sales, revenue & invoice records…"

    # Same domain: inventory
    inv_combined = get_parallel_tools_label(["stock_summary", "search_product"])
    assert inv_combined == "Checking inventory, stock & product details…"

    # Same domain: customers
    cust_combined = get_parallel_tools_label(["customer_summary", "get_customer_ledger"])
    assert cust_combined == "Fetching customer records & ledger balances…"

    # Cross domain: sales + finance
    cross_combined = get_parallel_tools_label(["today_sale", "expense_summary"])
    assert "sales" in cross_combined.lower()
    assert "expense" in cross_combined.lower()


def test_pure_conversational_queries_never_trigger_tools():
    """Verify that pure chit-chat queries do not trigger any store operations."""
    chitchat_queries = [
        "thik he tune bola to ruk jata hu",
        "theek hai baad me karenge",
        "ok ruk",
        "samajh gaya",
        "hello kaise ho",
        "good morning brother",
    ]
    for q in chitchat_queries:
        assert is_pure_chitchat(q), f"Expected '{q}' to be pure chitchat"
        intent = resolve_turn_intent(
            q,
            available=TOOL_METADATA_CATALOG.keys(),
        )
        assert intent.routing == "neither"
        assert len(intent.tool_names) == 0


def test_sensitive_action_typo_creates_confirmation():
    """Verify that common typos in sensitive actions are recognized for confirmation."""
    assert user_requested_sensitive_action("aaj ka exepnse add karo 500 tea", "create_expense")
    assert user_requested_sensitive_action("500 rupay expence likh do chai ka", "create_expense")
    assert user_requested_sensitive_action("new custmer banao ravi 9876543210", "create_customer")
    assert user_requested_sensitive_action("vikram ke khate me 100 add kar do", "ledger_debit")
    assert not user_requested_sensitive_action("vikram ke khate me 100 add kar do", "ledger_credit")
