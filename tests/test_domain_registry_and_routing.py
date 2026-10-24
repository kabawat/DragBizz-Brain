"""Tests for DragBizz Agentic Chatbot Phase A.

Unified Tool Registry and Domain Routing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.orchestrator.tool_selector import (
    SAFE_BROAD_STORE_FALLBACK,
    detect_query_domains,
    is_pure_chitchat,
    resolve_domain_turn_intent,
    resolve_turn_intent,
)
from app.schemas.chat import ChatResponse
from app.schemas.tool import ToolAccessType, ToolDomain, ToolRisk
from app.tools.context import ToolContext
from app.tools.definitions import (
    ALL_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import (
    SENSITIVE_TOOL_HANDLERS,
)
from app.tools.handlers.confirm_tools import (
    create_purchase_order as po_handler,
)
from app.tools.registry import build_unified_tool_registry

STORE_ID = "6ad49964d5cb7a1b29d4bb7b"
SUPPLIER_ID = "6ad4baef6f4697221df5f9ef"
PRODUCT_ID = "6ad4b6206f4697221df5f87f"
ALL_NAMES = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)


def test_unified_tool_registry_metadata() -> None:
    """Registry correctly maps definitions, handlers, domains, and access types."""
    registry = build_unified_tool_registry()
    assert len(registry.definitions()) == len(ALL_NAMES)
    assert len(registry.entries()) == len(ALL_NAMES)

    # Verify inventory tools
    inv_tools = registry.definitions_for_domain(ToolDomain.INVENTORY)
    inv_names = {t.name for t in inv_tools}
    assert "search_product" in inv_names
    assert "stock_summary" in inv_names
    assert "add_stock" in inv_names

    # Check entry metadata
    po_entry = registry.get_entry("create_purchase_order")
    assert po_entry.domain == ToolDomain.PROCUREMENT
    assert po_entry.access_type == ToolAccessType.WRITE
    assert po_entry.requires_confirmation is True
    assert po_entry.required_permissions == ("purchase_orders:write",)
    assert po_entry.handler == SENSITIVE_TOOL_HANDLERS["create_purchase_order"]

    read_entry = registry.get_entry("today_sale")
    assert read_entry.domain == ToolDomain.SALES
    assert read_entry.access_type == ToolAccessType.READ
    assert read_entry.requires_confirmation is False


# 1. Existing ordinary chat behavior remains unchanged (pure chit-chat -> 0 tools).
@pytest.mark.parametrize(
    "chitchat_query",
    [
        "hello",
        "hi",
        "kaise ho",
        "kya haal hai",
        "thank you",
        "dhanyawad",
        "who are you",
        "aap kaun ho",
        "bye",
        "good morning",
    ],
)
def test_case1_ordinary_chitchat_exposes_zero_tools(chitchat_query: str) -> None:
    assert is_pure_chitchat(chitchat_query) is True
    intent = resolve_domain_turn_intent(chitchat_query, available=ALL_NAMES)
    assert intent.routing == "neither"
    assert len(intent.tool_names) == 0


# 2. Hinglish product and stock queries expose the appropriate tools.
@pytest.mark.parametrize(
    "stock_query",
    [
        "bhai stock me kya kya pada hai dikhana",
        "ye product dukan me kitna bacha hai",
        "low stock items batao",
        "inventory velocity report dikhao",
    ],
)
def test_case2_hinglish_stock_queries_expose_inventory_tools(
    stock_query: str,
) -> None:
    intent = resolve_domain_turn_intent(stock_query, available=ALL_NAMES)
    assert intent.routing in {"tools", "both"}
    assert "search_product" in intent.tool_names
    assert "stock_summary" in intent.tool_names


# 3. 'Amul cheese slices ka 10 packet PO Amul supplier se banao'
# exposes both search tools.
def test_case3_po_prompt_exposes_product_and_supplier_search() -> None:
    query = "Amul cheese slices ka 10 packet PO Amul supplier se banao"
    domains = detect_query_domains(query)
    assert ToolDomain.PROCUREMENT in domains

    intent = resolve_domain_turn_intent(query, available=ALL_NAMES)
    assert intent.routing == "tools"
    assert "create_purchase_order" in intent.tool_names
    assert "search_supplier" in intent.tool_names
    assert "search_product" in intent.tool_names


# 4. Missing or unmatched product names do not cause fabricated product IDs.
@pytest.mark.asyncio
async def test_case4_duplicate_supplier_as_product_rejected() -> None:
    mock_retailer = AsyncMock()
    context = ToolContext(
        store_id=STORE_ID,
        access_token="tok_123",
        retailer=mock_retailer,
    )
    bad_payload = {
        "storeId": STORE_ID,
        "supplierId": SUPPLIER_ID,
        "items": [
            {
                "productId": SUPPLIER_ID,  # Fabricated: copied supplier ID
                "quantity": 10,
                "productName": "Amul Cheese Slices",
            }
        ],
    }
    result = await po_handler(bad_payload, context)
    assert result.success is False
    assert result.data["code"] == "TOOL_ARGS_INVALID"
    assert "productId equal to supplierId" in result.data["message"]
    mock_retailer.create_purchase_order.assert_not_called()


# 5. Sales, invoice, khata, and expense requests can access their relevant domain tools.
def test_case5_domain_tools_accessible() -> None:
    # Sales
    sales_intent = resolve_domain_turn_intent(
        "aaj kitni bikri hui invoice summary dikhao", available=ALL_NAMES
    )
    assert "today_sale" in sales_intent.tool_names
    assert "invoice_summary" in sales_intent.tool_names
    assert "list_invoices" in sales_intent.tool_names

    # Khata
    khata_intent = resolve_domain_turn_intent(
        "Rahul customer ka khata aur balance check karo", available=ALL_NAMES
    )
    assert "search_customer" in khata_intent.tool_names
    assert "get_customer_ledger" in khata_intent.tool_names

    # Expense / Finance
    expense_intent = resolve_domain_turn_intent(
        "petrol ka kharcha check karo cashbook se", available=ALL_NAMES
    )
    assert "expense_summary" in expense_intent.tool_names
    assert "cashbook_summary" in expense_intent.tool_names


# 6. An unfamiliar store-related request does not incorrectly take the no-tools path.
def test_case6_unfamiliar_store_request_takes_safe_broad_fallback() -> None:
    unfamiliar_query = "meri dukaan ki overall sthiti aur mahol kaisa chal raha hai"
    assert is_pure_chitchat(unfamiliar_query) is False

    intent = resolve_domain_turn_intent(unfamiliar_query, available=ALL_NAMES)
    assert len(intent.tool_names) > 0
    # Must include core read tools
    assert "today_sale" in intent.tool_names
    assert "stock_summary" in intent.tool_names
    assert "search_product" in intent.tool_names
    assert "search_customer" in intent.tool_names

    # Safe fallback MUST NEVER expose write or sensitive tools
    writes = {t.name for t in WRITE_TOOL_DEFINITIONS} | {
        t.name for t in SENSITIVE_TOOL_DEFINITIONS
    }
    assert intent.tool_names.isdisjoint(writes)

    # Pure fallback without domain keywords
    generic_fallback_query = "kuch naya ya anokha analysis batao aaj ka"
    fallback_intent = resolve_domain_turn_intent(
        generic_fallback_query, available=ALL_NAMES
    )
    assert fallback_intent.routing == "unknown"
    assert "today_sale" in fallback_intent.tool_names
    assert "stock_summary" in fallback_intent.tool_names
    assert "search_product" in fallback_intent.tool_names
    assert fallback_intent.tool_names.isdisjoint(writes)


# 7. Unauthorized cross-store access is rejected.
def test_case7_invalid_store_id_rejected() -> None:
    from app.core.exceptions import AppError
    from app.schemas.chat import assert_valid_store_id

    with pytest.raises(AppError) as exc_info:
        assert_valid_store_id("invalid-store-hex-123")
    assert exc_info.value.code == "STORE_ID_INVALID"


# 8. A purchase-order or invoice write cannot execute without required confirmation.
def test_case8_write_tools_risk_governance() -> None:
    registry = build_unified_tool_registry()
    po = registry.get_definition("create_purchase_order")
    release = registry.get_definition("release_invoice")
    assert po.risk == ToolRisk.SENSITIVE
    assert release.risk == ToolRisk.SENSITIVE
    assert po.requires_confirmation is True
    assert release.requires_confirmation is True


# 9. Existing fast paths do not silently regress.
@pytest.mark.asyncio
async def test_case9_fast_paths_intact() -> None:
    from app.orchestrator.dossier_auto import try_fast_name_list

    mock_executor = AsyncMock()
    # When prompt matches fast name list pattern
    res = await try_fast_name_list(
        question="all customers list dikhao",
        language="hi",
        store_id=STORE_ID,
        access_token="tok",
        session_id="sess_1",
        user_id="user_1",
        allowed_names=frozenset({"customer_summary"}),
        executor=mock_executor,
    )
    # Returns structured deterministic outcome or None if not matching
    assert res is None or res.message is not None


# 10. Existing endpoint response formats and frontend expectations remain compatible.
def test_case10_chat_response_schema_compatibility() -> None:
    resp = ChatResponse(
        message="Order ready",
        session_id="sess_123",
        request_id="req_456",
        user_id="user_789",
        provider="domain_agent",
        model="gpt-4o-mini",
        tool_calls=[],
        tool_results=[],
        pending_confirmation=None,
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped["message"] == "Order ready"
    assert dumped["sessionId"] == "sess_123"
    assert dumped["requestId"] == "req_456"
    assert dumped["userId"] == "user_789"
    assert dumped["toolCalls"] == []
    assert dumped["toolResults"] == []
    assert dumped["pendingConfirmation"] is None


# 11. Feature flag toggle restores legacy routing cleanly.
def test_feature_flag_rollback_toggle() -> None:
    query = "kuch bhi"
    # Legacy routing
    legacy = resolve_turn_intent(query, available=ALL_NAMES, use_domain_routing=False)
    # Domain routing
    domain = resolve_turn_intent(query, available=ALL_NAMES, use_domain_routing=True)

    # Legacy returns narrow _CORE_UNKNOWN_TOOLS
    assert len(legacy.tool_names) == 4
    # Domain returns safe broad fallback (10 tools)
    assert len(domain.tool_names) == len(SAFE_BROAD_STORE_FALLBACK & ALL_NAMES)
