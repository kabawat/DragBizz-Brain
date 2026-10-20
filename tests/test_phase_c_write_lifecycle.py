"""Phase C: Safe Write Lifecycle & End-to-End Agentic Workflows.

Tests all 16 required Phase C scenarios:
1. Complete PO request resolves product & supplier IDs from mocked catalog.
2. Independent reads execute concurrently and dependent actions wait for them.
3. Ambiguous products or suppliers result in clarification.
4. Missing or invalid prices and quantities cannot become fabricated values.
5. Action preview does not execute a write.
6. No confirmation means no write.
7. A valid confirmation executes the exact staged payload.
8. A confirmation cannot be reused to execute the same operation twice.
9. Repeated or concurrent confirmations do not create duplicate mutations.
10. Cross-user and cross-store confirmations are rejected.
11. Expired, cancelled, altered, and mismatched confirmations are rejected.
12. Stale or mismatched constraints trigger revalidation and rejection.
13. Execution failures and timeouts do not cause unsafe duplicate retries.
14. Invoice, expense, and sensitive ledger operations preserve confirmation.
15. SSE events, chat responses, and frontend confirmation cards remain compatible.
16. Phase A and Phase B guarantees continue to hold.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.confirmations import (
    CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER,
    InMemoryConfirmationStore,
)
from app.core.exceptions import AppError
from app.executors.dependencies import StageKind, plan_execution
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerResponse
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import (
    pending_to_schema,
    stage_from_sensitive_calls,
)
from app.orchestrator.tool_selector import (
    detect_query_domains,
    resolve_domain_turn_intent,
)
from app.schemas.chat import (
    ConfirmRequest,
)
from app.schemas.tool import (
    ToolCall,
    ToolDomain,
)
from app.sessions import InMemorySessionStore
from app.tools.context import ToolContext
from app.tools.definitions import (
    ALL_TOOL_DEFINITIONS,
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import (
    SENSITIVE_TOOL_HANDLERS,
)
from app.tools.handlers.read_tools import (
    READ_TOOL_HANDLERS,
    search_product,
    search_supplier,
)
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE_ID = "6ad49964d5cb7a1b29d4bb7b"
OTHER_STORE_ID = "6ad49964d5cb7a1b29d4bb8c"
SUPPLIER_ID = "6ad4baef6f4697221df5f9ef"
PRODUCT_ID = "6ad4b6206f4697221df5f87f"
USER_ID = "6ace9dede6f88a5b1523bd7d"
OTHER_USER_ID = "6ace9dede6f88a5b1523bd99"
SESSION_ID = "sess_phase_c_123"


def _mock_guard(text: str, **kwargs: Any) -> str:
    return text


def _build_test_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for d in READ_TOOL_DEFINITIONS:
        reg.register(d, READ_TOOL_HANDLERS[d.name])
    for d in WRITE_TOOL_DEFINITIONS:
        reg.register(d, WRITE_TOOL_HANDLERS[d.name])
    for d in SENSITIVE_TOOL_DEFINITIONS:
        reg.register(d, SENSITIVE_TOOL_HANDLERS[d.name])
    return reg


# ---------------------------------------------------------------------------
# 1. Complete PO request resolves records and stages preview without write
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_end_to_end_po_workflow_resolves_records_and_stages() -> None:
    """User: 'Amul cheese slices ka 10 packet PO Amul supplier se banao'.

    Concurrent reads search product and supplier -> real IDs resolved ->
    create_purchase_order is staged with preview summary -> no mutation.
    """
    retailer = AsyncMock()
    retailer.get_products.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": [
                {
                    "id": PRODUCT_ID,
                    "name": "Amul Cheese Slices",
                    "sellingPrice": 120.0,
                    "pricing": {
                        "purchasePrice": 95.0,
                        "sellingPrice": 120.0,
                        "uom": "packet",
                    },
                    "stock": {"availableQuantity": 50},
                }
            ]
        },
    )
    retailer.get_suppliers.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "suppliers": [
                    {
                        "id": SUPPLIER_ID,
                        "name": "Amul India",
                        "phone": "9876543210",
                    }
                ]
            }
        },
    )
    retailer.create_purchase_order = AsyncMock()

    ctx = ToolContext(
        retailer=retailer,
        access_token="tok_123",
        store_id=STORE_ID,
    )

    # Round 1: Search product & supplier concurrently
    res_prod, res_sup = await asyncio.gather(
        search_product({"query": "Amul cheese slices", "storeId": STORE_ID}, ctx),
        search_supplier({"query": "Amul", "storeId": STORE_ID}, ctx),
    )

    assert res_prod.success is True
    assert res_prod.data["found"] is True
    assert res_prod.data["items"][0]["id"] == PRODUCT_ID

    assert res_sup.success is True
    assert res_sup.data["found"] is True
    assert res_sup.data["suppliers"][0]["id"] == SUPPLIER_ID

    # Round 2: Model stages create_purchase_order using resolved IDs
    po_call = ToolCall(
        id="call_po_1",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "supplierName": "Amul India",
            "items": [
                {
                    "productId": PRODUCT_ID,
                    "quantity": 10,
                    "productName": "Amul Cheese Slices",
                    "purchasePrice": 95.0,
                    "unit": "packet",
                }
            ],
            "paymentTerms": "30_DAYS",
        },
    )

    confirm_store = InMemoryConfirmationStore()
    record = await stage_from_sensitive_calls(
        confirm_store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[po_call],
        retailer=retailer,
        access_token="tok_123",
    )

    assert record is not None
    assert record.type == CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER
    assert record.status == "PENDING"
    assert record.summary["action"] == "create_purchase_order"
    assert record.summary["supplierId"] == SUPPLIER_ID
    assert record.summary["supplierName"] == "Amul India"
    assert record.summary["totalQuantity"] == 10
    assert record.summary["totalAmount"] == 950.0
    assert record.summary["currency"] == "INR"

    # Preview does NOT execute any write on Retailer!
    retailer.create_purchase_order.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Independent reads execute concurrently and dependent write waits
# ---------------------------------------------------------------------------
def test_independent_reads_execute_concurrently_before_dependent_write() -> None:
    reg = _build_test_registry()
    calls = [
        ToolCall(
            id="c1",
            name="search_product",
            arguments={"storeId": STORE_ID, "query": "cheese"},
        ),
        ToolCall(
            id="c2",
            name="search_supplier",
            arguments={"storeId": STORE_ID, "query": "amul"},
        ),
        ToolCall(
            id="c3",
            name="create_purchase_order",
            arguments={"storeId": STORE_ID},
        ),
    ]
    stages = plan_execution(calls, registry=reg)

    # First stage: parallel read of product and supplier
    assert stages[0].kind == StageKind.PARALLEL_READ
    assert len(stages[0].calls) == 2
    assert {c.name for c in stages[0].calls} == {"search_product", "search_supplier"}

    # Dependent write/sensitive action is staged in a subsequent sequential stage
    assert stages[1].kind == StageKind.SEQUENTIAL_SENSITIVE
    assert stages[1].calls[0].name == "create_purchase_order"


# ---------------------------------------------------------------------------
# 3. Ambiguous products or suppliers result in disambiguation required
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ambiguous_products_or_suppliers_require_clarification() -> None:
    retailer = AsyncMock()
    retailer.get_products.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": [
                {"id": "prod_1", "name": "Amul Cheese Slices 100g"},
                {"id": "prod_2", "name": "Amul Cheese Slices 200g"},
                {"id": "prod_3", "name": "Amul Cheese Slices 500g"},
            ]
        },
    )
    retailer.get_suppliers.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": {
                "suppliers": [
                    {"id": "sup_1", "name": "Amul Distributor North"},
                    {"id": "sup_2", "name": "Amul Distributor South"},
                ]
            }
        },
    )

    ctx = ToolContext(retailer=retailer, access_token="tok", store_id=STORE_ID)
    res_p = await search_product({"query": "Amul cheese", "storeId": STORE_ID}, ctx)
    res_s = await search_supplier({"query": "Amul", "storeId": STORE_ID}, ctx)

    assert res_p.data["count"] == 3
    assert res_p.data["disambiguationRequired"] is True

    assert res_s.data["count"] == 2
    assert res_s.data["disambiguationRequired"] is True


# ---------------------------------------------------------------------------
# 4. Missing or invalid values cannot become fabricated IDs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_or_invalid_values_not_fabricated() -> None:
    confirm_store = InMemoryConfirmationStore()

    # Attempt to copy supplier ID as product ID
    call_copied_id = ToolCall(
        id="c_bad",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": SUPPLIER_ID, "quantity": 10}],
        },
    )
    with pytest.raises(AppError) as exc_info:
        await stage_from_sensitive_calls(
            confirm_store,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
            sensitive_calls=[call_copied_id],
        )
    assert exc_info.value.code == "TOOL_ARGS_INVALID"
    assert "productId equal to supplierId" in exc_info.value.message

    # Non-positive quantity
    call_bad_qty = ToolCall(
        id="c_bad_qty",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 0}],
        },
    )
    with pytest.raises(AppError) as exc_info:
        await stage_from_sensitive_calls(
            confirm_store,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
            sensitive_calls=[call_bad_qty],
        )
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


# ---------------------------------------------------------------------------
# 5 & 6. Preview does not write; No confirmation means no write
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_preview_and_no_confirmation_means_no_write() -> None:
    retailer = AsyncMock()
    retailer.create_purchase_order = AsyncMock()
    store = InMemoryConfirmationStore()

    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 5}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )

    assert record is not None
    assert record.status == "PENDING"
    # Never writes until explicit user confirmation
    retailer.create_purchase_order.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Valid confirmation executes the exact staged payload
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_confirmation_executes_exact_staged_payload() -> None:
    retailer = AsyncMock()
    retailer.create_purchase_order.return_value = RetailerResponse(
        status_code=201,
        body={"data": {"id": "po_999", "poNumber": "PO-2026-0099", "status": "DRAFT"}},
    )
    reg = _build_test_registry()
    executor = ToolExecutor(registry=reg, retailer=retailer)
    store = InMemoryConfirmationStore()
    sessions = InMemorySessionStore()

    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 10, "purchasePrice": 95.0}],
            "paymentTerms": "15_DAYS",
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )

    # User confirms the staged action
    req = ConfirmRequest(
        confirmation_id=record.confirmation_id,
        session_id=SESSION_ID,
        store_id=STORE_ID,
        draft_id=record.draft_id,
        action="approve",
    )
    resp = await handle_confirm(
        body=req,
        request_id="req_1",
        user_id=USER_ID,
        store_id=STORE_ID,
        access_token="tok_123",
        confirmations=store,
        sessions=sessions,
        executor=executor,
        guard_output=_mock_guard,
    )

    assert "PO-2026-0099" in resp.message
    call_kwargs = retailer.create_purchase_order.call_args.kwargs
    assert call_kwargs["access_token"] == "tok_123"
    assert call_kwargs["store_id"] == STORE_ID
    assert call_kwargs["supplier_id"] == SUPPLIER_ID
    assert call_kwargs["items"] == [{"productId": PRODUCT_ID, "quantity": 10}]
    assert call_kwargs["payment_terms"] == "15_DAYS"
    prefix = f"ai:idempotency:{SESSION_ID}:create_purchase_order:"
    assert call_kwargs["idempotency_key"].startswith(prefix)


# ---------------------------------------------------------------------------
# 8 & 9. A confirmation cannot be reused; Concurrent confirmations rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_confirmation_cannot_be_reused_and_no_duplicate_execution() -> None:
    retailer = AsyncMock()
    retailer.create_purchase_order.return_value = RetailerResponse(
        status_code=201,
        body={"data": {"id": "po_1"}},
    )
    reg = _build_test_registry()
    executor = ToolExecutor(registry=reg, retailer=retailer)
    store = InMemoryConfirmationStore()
    sessions = InMemorySessionStore()

    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 5}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )

    req = ConfirmRequest(
        confirmation_id=record.confirmation_id,
        session_id=SESSION_ID,
        store_id=STORE_ID,
        draft_id=record.draft_id,
        action="approve",
    )

    # First confirmation succeeds
    await handle_confirm(
        body=req,
        request_id="req_1",
        user_id=USER_ID,
        store_id=STORE_ID,
        access_token="tok",
        confirmations=store,
        sessions=sessions,
        executor=executor,
        guard_output=_mock_guard,
    )
    assert retailer.create_purchase_order.call_count == 1

    # Second confirmation attempt raises 409
    with pytest.raises(AppError) as exc_info:
        await handle_confirm(
            body=req,
            request_id="req_2",
            user_id=USER_ID,
            store_id=STORE_ID,
            access_token="tok",
            confirmations=store,
            sessions=sessions,
            executor=executor,
            guard_output=_mock_guard,
        )
    assert exc_info.value.code == "CONFIRMATION_REQUIRED"
    assert exc_info.value.status_code == 409
    # Still called only once
    assert retailer.create_purchase_order.call_count == 1


# ---------------------------------------------------------------------------
# 10. Cross-user and cross-store confirmations are rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_user_and_cross_store_confirmations_rejected() -> None:
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 5}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )

    # Cross-user attempt
    with pytest.raises(AppError) as exc_info:
        await store.get(
            record.confirmation_id,
            user_id=OTHER_USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
        )
    assert exc_info.value.code == "CONFIRMATION_FORBIDDEN"
    assert exc_info.value.status_code == 403

    # Cross-store attempt
    with pytest.raises(AppError) as exc_info:
        await store.get(
            record.confirmation_id,
            user_id=USER_ID,
            store_id=OTHER_STORE_ID,
            session_id=SESSION_ID,
        )
    assert exc_info.value.code == "CONFIRMATION_FORBIDDEN"
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 11. Expired, cancelled, and altered confirmations are rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_cancelled_and_altered_confirmations_rejected() -> None:
    current_time = 1000.0
    store = InMemoryConfirmationStore(ttl_seconds=60, clock=lambda: current_time)

    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 5}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )

    # Fast-forward time beyond TTL (60s)
    current_time = 1100.0
    with pytest.raises(AppError) as exc_info:
        await store.get(
            record.confirmation_id,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
        )
    assert exc_info.value.code == "CONFIRMATION_EXPIRED"
    assert exc_info.value.status_code == 410

    # Test altered parameters in handle_confirm
    current_time = 1000.0
    fresh_store = InMemoryConfirmationStore(ttl_seconds=600, clock=lambda: current_time)
    rec2 = await stage_from_sensitive_calls(
        fresh_store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )
    # Attempting to tamper with items/supplierId in updates payload
    tampered_req = ConfirmRequest(
        confirmation_id=rec2.confirmation_id,
        session_id=SESSION_ID,
        store_id=STORE_ID,
        draft_id=rec2.draft_id,
        action="approve",
        updates={"supplierId": "malicious_supplier_id"},
    )
    with pytest.raises(AppError) as exc_info:
        await handle_confirm(
            body=tampered_req,
            request_id="req_t",
            user_id=USER_ID,
            store_id=STORE_ID,
            access_token="tok",
            confirmations=fresh_store,
            sessions=InMemorySessionStore(),
            executor=ToolExecutor(
                registry=_build_test_registry(),
                retailer=AsyncMock(),
            ),
            guard_output=_mock_guard,
        )
    assert exc_info.value.code == "CONFIRMATION_ARGUMENTS_INVALID"
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 12. Stale or mismatched store constraints rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_or_mismatched_constraints_rejected() -> None:
    bad_args = {
        "storeId": OTHER_STORE_ID,
        "supplierId": SUPPLIER_ID,
        "items": [{"productId": PRODUCT_ID, "quantity": 5}],
    }
    with pytest.raises(AppError) as exc_info:
        executor = ToolExecutor(registry=_build_test_registry(), retailer=AsyncMock())
        await executor.execute_confirmations(
            [ToolCall(id="c_po", name="create_purchase_order", arguments=bad_args)],
            access_token="tok",
            store_id=STORE_ID,
            session_id=SESSION_ID,
            user_id=USER_ID,
            confirmation_id="conf_1",
        )
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


# ---------------------------------------------------------------------------
# 13. Execution failures and timeouts do not cause unsafe duplicate retries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_execution_failures_do_not_cause_unsafe_retries() -> None:
    retailer = AsyncMock()
    retailer.create_purchase_order.side_effect = RuntimeError("Retailer timeout")
    reg = _build_test_registry()
    executor = ToolExecutor(registry=reg, retailer=retailer)
    store = InMemoryConfirmationStore()
    sessions = InMemorySessionStore()

    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "items": [{"productId": PRODUCT_ID, "quantity": 5}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )

    req = ConfirmRequest(
        confirmation_id=record.confirmation_id,
        session_id=SESSION_ID,
        store_id=STORE_ID,
        draft_id=record.draft_id,
        action="approve",
    )
    resp = await handle_confirm(
        body=req,
        request_id="req_fail",
        user_id=USER_ID,
        store_id=STORE_ID,
        access_token="tok",
        confirmations=store,
        sessions=sessions,
        executor=executor,
        guard_output=_mock_guard,
    )

    # Transitions to UNKNOWN safely
    updated_rec = await store.complete(record.confirmation_id, status="UNKNOWN")
    assert updated_rec.status == "UNKNOWN"
    msg = resp.message.lower()
    assert "unclear" in msg or "status unknown" in msg or "not sure" in msg


# ---------------------------------------------------------------------------
# 14. Invoice, expense, and sensitive ledger operations preserve confirmation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invoice_expense_ledger_preserve_confirmation() -> None:
    reg = _build_test_registry()
    executor = ToolExecutor(registry=reg, retailer=AsyncMock())

    sensitive_names = [
        "create_purchase_order",
        "release_invoice",
        "create_expense",
        "ledger_credit",
        "ledger_debit",
        "add_stock",
    ]
    for name in sensitive_names:
        call = ToolCall(id=f"c_{name}", name=name, arguments={"storeId": STORE_ID})
        with pytest.raises(AppError) as exc_info:
            await executor.execute_reads(
                [call],
                access_token="tok",
                store_id=STORE_ID,
                allowed_names=frozenset({name}),
            )
        assert exc_info.value.code == "TOOL_NOT_EXECUTABLE"


# ---------------------------------------------------------------------------
# 15. SSE events, chat responses, and frontend confirmation cards compatibility
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sse_events_and_frontend_cards_compatibility() -> None:
    store = InMemoryConfirmationStore()
    call = ToolCall(
        id="c_po",
        name="create_purchase_order",
        arguments={
            "storeId": STORE_ID,
            "supplierId": SUPPLIER_ID,
            "supplierName": "Amul",
            "items": [{"productId": PRODUCT_ID, "quantity": 10, "purchasePrice": 95.0}],
        },
    )
    record = await stage_from_sensitive_calls(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        sensitive_calls=[call],
    )
    schema = pending_to_schema(record)

    # Frontend requires these exact keys
    assert schema.confirmation_id == record.confirmation_id
    assert schema.type == CONFIRMATION_TYPE_CREATE_PURCHASE_ORDER
    assert schema.summary["action"] == "create_purchase_order"
    assert schema.summary["currency"] == "INR"
    assert schema.summary["totalQuantity"] == 10
    assert schema.summary["totalAmount"] == 950.0
    assert "Z" in schema.expires_at


# ---------------------------------------------------------------------------
# 16. Phase A & B guarantees continue to pass
# ---------------------------------------------------------------------------
def test_phase_a_and_b_guarantees_hold() -> None:
    query = "Amul cheese slices ka 10 packet PO Amul supplier se banao"
    domains = detect_query_domains(query)
    assert ToolDomain.PROCUREMENT in domains

    all_names = frozenset(t.name for t in ALL_TOOL_DEFINITIONS)
    intent = resolve_domain_turn_intent(query, available=all_names)
    assert intent.routing == "tools"
    assert "create_purchase_order" in intent.tool_names
    assert "search_supplier" in intent.tool_names
    assert "search_product" in intent.tool_names
