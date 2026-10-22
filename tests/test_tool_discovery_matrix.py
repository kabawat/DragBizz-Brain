"""Systematic Registry-Wide Coverage & Typo-Tolerant Hybrid Tool Retrieval Tests.

Validates that all 50 registered tools across all 6 business domains are discoverable,
multilingual expressions (English, Hindi, Hinglish) and common typos resolve properly,
read/write distinctions and sensitive confirmation checks remain strictly governed,
and candidate tool counts remain bounded.
"""

from __future__ import annotations

import pytest

from app.orchestrator.tool_discovery import (
    GLOBAL_TOOL_RETRIEVER,
    TOOL_METADATA_CATALOG,
    ActionType,
)
from app.orchestrator.tool_selector import (
    resolve_domain_turn_intent,
    resolve_turn_intent,
    user_requested_sensitive_action,
)
from app.schemas.tool import ToolAccessType, ToolDomain
from app.tools.registry import build_unified_tool_registry

REGISTRY = build_unified_tool_registry()
ALL_DEFINITIONS = REGISTRY.definitions()
ALL_ENTRIES = REGISTRY.entries()
ALL_NAMES = frozenset(d.name for d in ALL_DEFINITIONS)


def test_registry_wide_metadata_completeness() -> None:
    """Verify that every single registered tool has complete discoverability metadata."""
    assert len(ALL_NAMES) == 50
    assert len(TOOL_METADATA_CATALOG) == 50

    uncovered_tools = ALL_NAMES - set(TOOL_METADATA_CATALOG.keys())
    assert not uncovered_tools, f"Uncovered registered tools found: {uncovered_tools}"

    for name in ALL_NAMES:
        meta = TOOL_METADATA_CATALOG[name]
        assert meta.name == name
        assert isinstance(meta.domain, ToolDomain)
        assert isinstance(meta.action_type, ActionType)
        assert meta.entity_type
        assert len(meta.aliases) > 0, f"Tool {name} has no aliases registered"


@pytest.mark.parametrize("tool_name", sorted(list(ALL_NAMES)))
def test_all_50_tools_discoverable_by_canonical_name(tool_name: str) -> None:
    """Every registered tool must be discoverable using its canonical name or natural phrase."""
    meta = TOOL_METADATA_CATALOG[tool_name]
    query = f"please run {tool_name.replace('_', ' ')}"
    candidates = GLOBAL_TOOL_RETRIEVER.retrieve_candidates(
        query, available_tools=ALL_NAMES, limit=5
    )
    candidate_names = [c.tool_name for c in candidates]
    assert tool_name in candidate_names, (
        f"Tool '{tool_name}' failed to be retrieved by canonical query: '{query}'. "
        f"Retrieved: {candidate_names}"
    )


TYPO_AND_MULTILINGUAL_TEST_MATRIX = [
    # Customer typo & Hinglish cases (Khata domain)
    ("crearte a custiomer name viksa test his email is vkkkmis@fda.ss", "create_customer"),
    ("craete customer name Rahul", "create_customer"),
    ("add custmer Rahul", "create_customer"),
    ("naya customer banao", "create_customer"),
    ("customer add karna hai", "create_customer"),
    ("show customer dues", "list_customer_accounts"),
    ("kiska baki hisab hai", "list_customer_accounts"),
    ("customer search karo Ramesh", "search_customer"),
    ("customer ka full dossier dikhao", "customer_dossier"),
    ("top spending customers report", "top_customers"),
    ("khata me 500 jama karo", "ledger_credit"),
    ("udhaar add kar do 200", "ledger_debit"),
    ("payment collect link banao", "create_collect_link"),
    ("payment reminder bhejo", "send_payment_reminder"),
    ("opening balance set karo 1000", "set_opening_balance"),

    # Inventory typo & Hinglish cases (Inventory domain)
    ("shwo stcok summary", "stock_summary"),
    ("stcok kitna bacha hai", "stock_summary"),
    ("add stcok for maggi 10 units", "add_stock"),
    ("stock intake 50 packet", "add_stock"),
    ("low stcok items list", "stock_items"),
    ("pruduct search maggi", "search_product"),
    ("total catalog items kitne hai", "product_summary"),
    ("inventory velocity report", "inventory_velocity"),

    # Sales typo & Hinglish cases (Sales domain)
    ("invoce list dikhao", "list_invoices"),
    ("naya bill banao", "create_invoice_draft"),
    ("craete invoice draft for customer", "create_invoice_draft"),
    ("bill release karo", "release_invoice"),
    ("aaj ki live sale batao", "today_sale"),
    ("sales pareto 80 20 report", "sales_pareto"),
    ("sales orders list", "list_sales_orders"),
    ("detailed sales analytics", "invoice_detailed_analytics"),

    # Finance typo & Hinglish cases (Finance domain)
    ("exepnse add karo 500 chai", "create_expense"),
    ("kharcha dalo 2000 rent", "create_expense"),
    ("total kharcha summary", "expense_summary"),
    ("purane kharche dikhao", "list_expenses"),
    ("galla cashbook summary", "cashbook_summary"),
    ("gst tax summary report", "gst_summary"),

    # Procurement typo & Hinglish cases (Procurement domain)
    ("suplier search Ramesh", "search_supplier"),
    ("vendor summary report", "supplier_summary"),
    ("po draft banao", "create_purchase_order"),
    ("purchase orders list dikhao", "list_purchase_orders"),
    ("supplier purchase bill summary", "bill_summary"),

    # General store ops cases (General domain)
    ("store staff members list", "list_staff"),
    ("meri dukane list karo", "list_stores"),
    ("store ka daily brief dikhao", "store_brief"),
]


@pytest.mark.parametrize("query,expected_tool", TYPO_AND_MULTILINGUAL_TEST_MATRIX)
def test_matrix_typo_and_multilingual_discovery(query: str, expected_tool: str) -> None:
    """Verify that typos, Hindi, and Hinglish across all domains discover the expected tool."""
    intent_domain = resolve_domain_turn_intent(query, available=ALL_NAMES)
    intent_default = resolve_turn_intent(query, available=ALL_NAMES, use_domain_routing=False)

    assert expected_tool in intent_domain.tool_names or expected_tool in intent_default.tool_names, (
        f"Query '{query}' failed to retrieve '{expected_tool}'. "
        f"Domain intent tools: {intent_domain.tool_names}, "
        f"Default intent tools: {intent_default.tool_names}"
    )


def test_reproduction_query_end_to_end_candidate_selection() -> None:
    """Explicitly verify reproduction query: crearte a custiomer name viksa test his email is vkkkmis@fda.ss"""
    repro_q = "crearte a custiomer name viksa test his email is vkkkmis@fda.ss"

    res_default = resolve_turn_intent(repro_q, available=ALL_NAMES, use_domain_routing=False)
    assert "create_customer" in res_default.tool_names
    assert len(res_default.tool_names) <= 8

    res_domain = resolve_domain_turn_intent(repro_q, available=ALL_NAMES)
    assert "create_customer" in res_domain.tool_names
    assert len(res_domain.tool_names) <= 12


def test_negation_blocks_mutation_candidate_exposure() -> None:
    """Negative instructions must not trigger mutation write tool exposure."""
    negative_queries = [
        "Do not create this customer",
        "dont create customer Rahul",
        "customer mat banao",
        "customer create mat karo",
        "add mat karo stock",
    ]
    for q in negative_queries:
        intent = resolve_domain_turn_intent(q, available=ALL_NAMES)
        assert "create_customer" not in intent.tool_names
        assert "add_stock" not in intent.tool_names


def test_how_to_informational_query_routes_to_docs() -> None:
    """Informational questions ('how to') must not trigger mutation tool staging."""
    info_queries = [
        "How do I create a customer?",
        "How to add stock?",
        "Customer create karne ka tarika kya hai kaise karein",
    ]
    for q in info_queries:
        intent = resolve_turn_intent(q, available=ALL_NAMES, use_domain_routing=False)
        assert intent.routing in {"docs", "both"}
        assert "create_customer" not in intent.tool_names


def test_sensitive_confirmation_guard_is_preserved() -> None:
    """Sensitive mutations require explicit action wording before staging."""
    assert user_requested_sensitive_action("ledger debit karo 100", "ledger_debit") is True
    assert user_requested_sensitive_action("khate me 100 add kar do", "ledger_debit") is True
    assert user_requested_sensitive_action("customer balance kitna hai", "ledger_debit") is False
    assert user_requested_sensitive_action("add 10 stock to product", "add_stock") is True
    assert user_requested_sensitive_action("stock summary batao", "add_stock") is False


def test_bounded_tool_candidate_counts() -> None:
    """Tool candidate sets must stay bounded and not indiscriminately expose all 50 tools."""
    for query, _ in TYPO_AND_MULTILINGUAL_TEST_MATRIX[:15]:
        intent = resolve_domain_turn_intent(query, available=ALL_NAMES)
        assert len(intent.tool_names) <= 15, f"Candidate set too large ({len(intent.tool_names)}) for '{query}'"
