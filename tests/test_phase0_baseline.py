"""Phase 0 baseline: registry inventory and isolated synthetic test fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.orchestrator.tool_selector import (
    resolve_domain_turn_intent,
    resolve_turn_intent,
)
from app.rag.chunker import chunk_markdown
from app.schemas.tool import ToolAccessType
from app.tools.registry import build_unified_tool_registry

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/phase0/staging_dataset.json"
CASES_PATH = ROOT / "docs/phase0/regression_cases.json"
INVENTORY_PATH = ROOT / "docs/phase0/capability_inventory.json"
KNOWLEDGE_INVENTORY_PATH = ROOT / "docs/phase0/knowledge_inventory.json"
UI_INVENTORY_PATH = ROOT / "docs/phase0/ui_surface_inventory.json"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _tenant(name: str) -> dict:
    return next(
        item for item in _fixture()["tenants"] if item["store_name"].endswith(name)
    )


def test_inventory_lists_every_registered_tool_once() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    registry = build_unified_tool_registry()
    names = [item["name"] for item in inventory]

    assert len(names) == len(set(names))
    assert set(names) == {entry.name for entry in registry.entries()}
    assert len(names) == 50


def test_inventory_reflects_runtime_registry() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    entries = {entry.name: entry for entry in build_unified_tool_registry().entries()}

    for item in inventory:
        entry = entries[item["name"]]
        assert item["registered_at_startup"] is True
        assert item["domain"] == entry.domain.value
        assert item["access"] == entry.access_type.value
        assert item["risk"] == entry.definition.risk.value
        assert item["requires_confirmation"] == entry.requires_confirmation
        assert item["required_permissions"] == list(entry.required_permissions)
        assert item["effective_user_authorization"] == "runtime permission dependent"
        assert item["execution_verified_by_inventory"] is False
        assert item["handler"]
        assert item["input_schema"]["type"] == "object"


def test_sensitive_tools_are_confirmation_gated() -> None:
    entries = build_unified_tool_registry().entries()
    sensitive = [
        entry for entry in entries if entry.definition.risk.value == "sensitive"
    ]
    assert sensitive
    assert all(entry.access_type == ToolAccessType.WRITE for entry in sensitive)
    assert all(entry.requires_confirmation for entry in sensitive)


def test_owner_and_read_only_roles_have_distinct_fixture_permissions() -> None:
    alpha = _tenant("Alpha")
    owner = next(user for user in alpha["users"] if user["role"] == "owner")
    reader = next(user for user in alpha["users"] if user["role"] == "read_only")
    assert "expenses:write" in owner["permissions"]
    assert "expenses:write" not in reader["permissions"]
    assert "inventory:write" in owner["permissions"]
    assert "inventory:write" not in reader["permissions"]


def test_fixture_has_isolated_tenants() -> None:
    tenants = _fixture()["tenants"]
    assert len(tenants) >= 2
    assert len({item["tenant_id"] for item in tenants}) == len(tenants)
    assert len({item["store_id"] for item in tenants}) == len(tenants)

    alpha, beta = tenants
    assert alpha["tenant_id"] != beta["tenant_id"]
    # Repeated ids catch code that filters by ID but omits store scope.
    assert alpha["customers"][0]["id"] == beta["customers"][0]["id"]
    assert alpha["products"][0]["id"] == beta["products"][0]["id"]
    assert alpha["customers"][0]["balance_due"] != beta["customers"][0]["balance_due"]


def test_missing_customer_case_is_privacy_scoped() -> None:
    alpha = _tenant("Alpha")
    matches = [
        customer
        for customer in alpha["customers"]
        if customer["name"].casefold() == "dragai qa 20261024"
    ]
    assert matches == []


def test_duplicate_customers_exist_for_ambiguity_case() -> None:
    alpha = _tenant("Alpha")
    matches = [
        customer
        for customer in alpha["customers"]
        if customer["name"].casefold() == "rohit sharma"
    ]
    assert len(matches) == 2
    assert len({customer["id"] for customer in matches}) == 2


def test_fixture_contains_hinglish_product_aliases() -> None:
    products = _tenant("Alpha")["products"]
    aliases = {alias for product in products for alias in product["aliases"]}
    assert {"atta", "aata", "आटा", "tel", "oil", "तेल"} <= aliases


def test_stock_fixture_covers_zero_and_negative_cases() -> None:
    products = _tenant("Alpha")["products"]
    quantities = {product["available_quantity"] for product in products}
    assert 0 in quantities
    assert any(quantity < 0 for quantity in quantities)
    expected = _fixture()["expected"]["alpha_out_of_stock_product_ids"]
    actual = [
        product["id"]
        for product in products
        if product["available_quantity"] <= 0
    ]
    assert actual == expected


def test_expense_fixture_total_reconciles() -> None:
    expenses = _tenant("Alpha")["expenses"]
    unpaid = [expense for expense in expenses if expense["status"] == "unpaid"]
    expected = _fixture()["expected"]
    assert len(unpaid) == expected["alpha_unpaid_expense_count"]
    assert sum(item["amount"] for item in unpaid) == expected[
        "alpha_unpaid_expense_total"
    ]


def test_invoice_fixture_exercises_pagination_and_long_ids() -> None:
    invoices = _tenant("Alpha")["invoices"]
    expected = _fixture()["expected"]
    assert len(invoices) == expected["alpha_invoice_count"]
    assert len(invoices[:3]) == expected["alpha_invoice_first_page_count"]
    assert max(len(invoice["number"]) for invoice in invoices) > 24
    assert {invoice["status"] for invoice in invoices} >= {"paid", "partial", "unpaid"}
    assert all(invoice["items"] for invoice in invoices)


def test_cashbook_fixture_has_explicit_expected_values() -> None:
    cashbook = _tenant("Alpha")["cashbook"]
    expected_closing = (
        cashbook["opening"] + cashbook["cash_in"] - cashbook["cash_out"]
    )
    assert expected_closing == cashbook["closing"]
    assert expected_closing == _fixture()["expected"]["alpha_cashbook_closing"]


def test_supplier_bills_and_purchase_orders_are_distinct() -> None:
    alpha = _tenant("Alpha")
    expected = _fixture()["expected"]
    assert len(alpha["supplier_bills"]) == expected["alpha_supplier_bill_count"]
    assert len(alpha["purchase_orders"]) == expected["alpha_purchase_order_count"]
    assert alpha["supplier_bills"][0]["id"] != alpha["purchase_orders"][0]["id"]
    assert alpha["supplier_bills"][0]["status"] != alpha["purchase_orders"][0]["status"]


def test_fixture_files_are_synthetic_only() -> None:
    fixture = _fixture()
    assert fixture["synthetic_only"] is True
    for tenant in fixture["tenants"]:
        for customer in tenant["customers"]:
            assert customer["email"].endswith("@example.invalid")
            assert customer["phone"].startswith("900000")


def test_fixture_includes_empty_error_and_pagination_scenarios() -> None:
    fixture = _fixture()
    states = {case["result_state"] for case in fixture["failure_scenarios"]}
    assert {"success_empty", "dependency_error", "unauthorized"} <= states
    assert fixture["pagination"]["total_count"] > fixture["pagination"]["page_size"]
    assert fixture["pagination"]["has_more"] is True


def test_knowledge_manifest_matches_checkout_sources() -> None:
    inventory = json.loads(KNOWLEDGE_INVENTORY_PATH.read_text(encoding="utf-8"))
    current_sources = sorted(
        path.relative_to(ROOT / "knowledge").as_posix()
        for path in (ROOT / "knowledge").rglob("*.md")
    )
    assert [item["source"] for item in inventory] == current_sources
    for item in inventory:
        source_path = ROOT / "knowledge" / item["source"]
        source_bytes = source_path.read_bytes()
        chunks = chunk_markdown(
            source_bytes.decode("utf-8"), source=item["source"]
        )
        assert item["sha256"] == hashlib.sha256(source_bytes).hexdigest()
        assert item["bytes"] == len(source_bytes)
        assert item["chunk_count"] == len(chunks)
    assert all(item["execution_verified"] is False for item in inventory)


def test_ui_surface_candidates_exist_but_remain_unverified() -> None:
    surface = json.loads(UI_INVENTORY_PATH.read_text(encoding="utf-8"))
    registered = {entry.name for entry in build_unified_tool_registry().entries()}
    for command in surface["commands"]:
        assert command["command"].startswith("/")
        assert command["status"] == "visible_unverified"
        assert set(command["candidate_tools"]) <= registered


def test_regression_catalog_covers_all_phase0_findings() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    assert {f"F-{number:02d}" for number in range(1, 13)} <= {
        case["finding"] for case in cases
    }
    assert all(case["prompt"] and case["expected"] and case["oracle"] for case in cases)
    assert all(case["fixture_check"].startswith("tests/") for case in cases)


def test_store_profile_fact_does_not_route_to_product_documentation() -> None:
    available = {entry.name for entry in build_unified_tool_registry().entries()}
    for resolver in (resolve_turn_intent, resolve_domain_turn_intent):
        for question in (
            "store ka naam kya hai",
            "mere store ki category kya hain",
            "how many stores do I have",
            "category ke according batao na",
        ):
            intent = resolver(question, available=available)
            assert intent.routing == "tools", question
            assert intent.tool_names == frozenset({"list_stores"}), question
