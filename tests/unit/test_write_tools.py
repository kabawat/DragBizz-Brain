"""Phase 4 — write tools + idempotency."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest

from app.core.exceptions import AppError
from app.core.logging import JsonFormatter
from app.executors.tool_executor import ToolExecutor
from app.idempotency import InMemoryIdempotencyStore, build_idempotency_key
from app.integrations.retailer_client import RetailerClient
from app.schemas.tool import ToolCall
from app.tools.context import ToolContext
from app.tools.definitions import READ_TOOL_DEFINITIONS, WRITE_TOOL_DEFINITIONS
from app.tools.handlers import write_tools
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.ledger_mapping import LEDGER_CREDIT_TYPE, LEDGER_DEBIT_TYPE
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"
CUSTOMER_ID = "607f1f77bcf86cd799439011"
PRODUCT_ID = "707f1f77bcf86cd799439011"
SESSION_ID = "session-1"
USER_ID = "user-1"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register(definition, READ_TOOL_HANDLERS[definition.name])
    for definition in WRITE_TOOL_DEFINITIONS:
        registry.register(definition, WRITE_TOOL_HANDLERS[definition.name])
    return registry


def _executor(
    retailer: RetailerClient,
    store: InMemoryIdempotencyStore | None = None,
) -> ToolExecutor:
    return ToolExecutor(
        registry=_registry(),
        retailer=retailer,
        idempotency_store=store or InMemoryIdempotencyStore(),
    )


# -------------------------------------------------------------- mapping


def test_ledger_mapping_constants() -> None:
    assert LEDGER_CREDIT_TYPE == "PAYMENT"
    assert LEDGER_DEBIT_TYPE == "DEBIT"


# -------------------------------------------------------------- retailer


def test_create_customer_posts_store_and_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["store"] = request.url.params.get("store")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            json={
                "data": {
                    "customer": {"id": CUSTOMER_ID, "name": "Ramesh"}
                }
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            result = await retailer.create_customer(
                access_token="token",
                store_id=STORE_ID,
                name="Ramesh",
                phone="9876543210",
            )
        assert result.status_code == 201

    asyncio.run(run())
    assert seen["method"] == "POST"
    assert seen["path"] == "/customer"
    assert seen["store"] == STORE_ID
    assert seen["body"]["store"] == STORE_ID
    assert seen["body"]["phone"] == "9876543210"
    assert seen["body"]["source"] == "VOICE_AI"


def test_create_customer_conflict_recovers_existing_customer() -> None:
    """409 duplicate → handler looks up the existing customer by phone
    and returns success with the real id (so the LLM never falls back
    to a walk-in invoice)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                409,
                json={
                    "message": (
                        "Customer already exists with same phone or email"
                    )
                },
            )
        assert request.url.params.get("search") == "8796766787"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": CUSTOMER_ID,
                        "name": "Nirma Kabwat",
                        "phone": "8796766787",
                    }
                ]
            },
        )

    async def run() -> Any:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            context = ToolContext(
                access_token="token",
                store_id=STORE_ID,
                retailer=retailer,
            )
            return await write_tools.create_customer(
                {
                    "storeId": STORE_ID,
                    "name": "Nirma Kabwat",
                    "phone": "8796766787",
                },
                context,
            )

    result = asyncio.run(run())
    assert result.success is True
    assert result.data["existing"] is True
    assert result.data["customer"]["id"] == CUSTOMER_ID
    assert result.data["openPath"] == f"/dashboard/customers/{CUSTOMER_ID}"


def test_create_customer_conflict_without_match_stays_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, json={"message": "already exists"})
        return httpx.Response(200, json={"data": []})

    async def run() -> Any:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            context = ToolContext(
                access_token="token",
                store_id=STORE_ID,
                retailer=retailer,
            )
            return await write_tools.create_customer(
                {
                    "storeId": STORE_ID,
                    "name": "Nirma Kabwat",
                    "phone": "8796766787",
                },
                context,
            )

    result = asyncio.run(run())
    assert result.success is False
    assert result.data["code"] == "TOOL_CONFLICT"


def test_ledger_credit_sends_payment_type() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"id": "txn1"}})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            await retailer.create_ledger_transaction(
                access_token="token",
                store_id=STORE_ID,
                customer_id=CUSTOMER_ID,
                transaction_type="PAYMENT",
                amount=100.0,
                idempotency_key="key-1",
            )

    asyncio.run(run())
    assert seen["body"]["type"] == "PAYMENT"
    assert seen["body"]["idempotencyKey"] == "key-1"
    assert seen["body"]["amount"] == 100.0


def test_create_invoice_draft_posts_items() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        assert "/release" not in request.url.path
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "inv1",
                    "invoiceStatus": "DRAFT",
                    "paymentStatus": "UNPAID",
                }
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            result = await retailer.create_invoice_draft(
                access_token="token",
                store_id=STORE_ID,
                items=[{"product": PRODUCT_ID, "quantity": 2}],
                is_walkin=True,
            )
        assert result.body["data"]["invoiceStatus"] == "DRAFT"

    asyncio.run(run())
    assert seen["path"] == "/invoices"
    assert seen["body"]["items"][0]["product"] == PRODUCT_ID


# -------------------------------------------------------------- executor


def test_write_executor_create_customer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={"data": {"customer": {"id": CUSTOMER_ID, "name": "Ramesh"}}},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            results = await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="create_customer",
                        arguments={
                            "storeId": STORE_ID,
                            "name": "Ramesh",
                            "phone": "9876543210",
                        },
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
        assert results[0].success is True
        assert results[0].data["customer"]["id"] == CUSTOMER_ID
        assert (
            results[0].data["openPath"] == f"/dashboard/customers/{CUSTOMER_ID}"
        )

    asyncio.run(run())


def test_ledger_credit_maps_to_payment_in_executor() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"id": "txn1", "type": "PAYMENT"}})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            results = await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="ledger_credit",
                        arguments={
                            "storeId": STORE_ID,
                            "customerId": CUSTOMER_ID,
                            "amount": 250,
                        },
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
        assert results[0].success is True

    asyncio.run(run())
    assert seen["body"]["type"] == "PAYMENT"
    assert "idempotencyKey" in seen["body"]


def test_ledger_debit_maps_to_debit() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"id": "txn2"}})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="ledger_debit",
                        arguments={
                            "storeId": STORE_ID,
                            "customerId": CUSTOMER_ID,
                            "amount": 50,
                        },
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )

    asyncio.run(run())
    assert seen["body"]["type"] == "DEBIT"


def test_duplicate_idempotency_replays_without_second_post() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            201,
            json={"data": {"customer": {"id": CUSTOMER_ID, "name": "Ramesh"}}},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        store = InMemoryIdempotencyStore()
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = _executor(retailer, store)
            call = ToolCall(
                id="1",
                name="create_customer",
                arguments={
                    "storeId": STORE_ID,
                    "name": "Ramesh",
                    "phone": "9876543210",
                },
            )
            first = await executor.execute_writes(
                [call],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
            second = await executor.execute_writes(
                [call],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
        assert first[0].success is True
        assert second[0].success is True
        assert second[0].data == first[0].data

    asyncio.run(run())
    assert calls["n"] == 1


def test_write_409_maps_to_conflict_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"message": "Customer already exists"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            results = await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="create_customer",
                        arguments={
                            "storeId": STORE_ID,
                            "name": "Ramesh",
                            "phone": "9876543210",
                        },
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
        assert results[0].success is False
        assert results[0].data["code"] == "TOOL_CONFLICT"

    asyncio.run(run())


def test_execute_writes_rejects_read_tool() -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            retailer = RetailerClient(client, "http://retailer.test")
            with pytest.raises(AppError) as exc:
                await _executor(retailer).execute_writes(
                    [
                        ToolCall(
                            id="1",
                            name="today_sale",
                            arguments={"storeId": STORE_ID},
                        )
                    ],
                    access_token="token",
                    store_id=STORE_ID,
                    session_id=SESSION_ID,
                    user_id=USER_ID,
                )
        assert exc.value.code == "TOOL_NOT_EXECUTABLE"

    asyncio.run(run())


def test_create_customer_requires_phone_or_email() -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            retailer = RetailerClient(client, "http://retailer.test")
            results = await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="create_customer",
                        arguments={"storeId": STORE_ID, "name": "Ramesh"},
                    )
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
        assert results[0].success is False
        assert results[0].data["code"] == "TOOL_ARGS_INVALID"

    asyncio.run(run())


def test_write_audit_log_has_no_phone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={"data": {"customer": {"id": CUSTOMER_ID}}},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            with caplog.at_level(logging.INFO):
                await _executor(retailer).execute_writes(
                    [
                        ToolCall(
                            id="1",
                            name="create_customer",
                            arguments={
                                "storeId": STORE_ID,
                                "name": "Ramesh",
                                "phone": "9876543210",
                            },
                        )
                    ],
                    access_token="token",
                    store_id=STORE_ID,
                    session_id=SESSION_ID,
                    user_id=USER_ID,
                )

    asyncio.run(run())
    audit_records = [
        r for r in caplog.records if r.getMessage() == "Tool execution audit"
    ]
    assert audit_records
    record = audit_records[0]
    assert record.audit["tool"] == "create_customer"
    assert record.audit["sessionId"] == SESSION_ID
    assert record.audit["success"] is True
    formatted = JsonFormatter().format(record)
    assert "9876543210" not in formatted
    assert "Ramesh" not in formatted


def test_idempotency_key_stable() -> None:
    args = {"storeId": STORE_ID, "name": "A", "phone": "9876543210"}
    a = build_idempotency_key(
        session_id=SESSION_ID, tool_name="create_customer", arguments=args
    )
    b = build_idempotency_key(
        session_id=SESSION_ID, tool_name="create_customer", arguments=args
    )
    assert a == b
    assert a.startswith(f"ai:{SESSION_ID}:create_customer:")


def test_only_one_invoice_draft_per_turn() -> None:
    """Duplicate draft calls with different args must not create two invoices."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            201,
            json={"data": {"id": f"inv{calls['n']}", "invoiceStatus": "DRAFT"}},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            results = await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="create_invoice_draft",
                        arguments={
                            "storeId": STORE_ID,
                            "items": [{"product": PRODUCT_ID, "quantity": 1}],
                        },
                    ),
                    ToolCall(
                        id="2",
                        name="create_invoice_draft",
                        arguments={
                            "storeId": STORE_ID,
                            "items": [{"product": PRODUCT_ID, "quantity": 2}],
                        },
                    ),
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
            )
        assert calls["n"] == 1  # retailer hit once
        assert results[0].success is True
        assert results[1].success is False
        assert results[1].data["code"] == "DUPLICATE_DRAFT_CALL"

    asyncio.run(run())


def test_draft_guard_spans_tool_rounds() -> None:
    """A draft created in an earlier round of the same turn blocks another
    create_invoice_draft in a later round (prior_successful_drafts)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            201,
            json={"data": {"id": "inv-x", "invoiceStatus": "DRAFT"}},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            results = await _executor(retailer).execute_writes(
                [
                    ToolCall(
                        id="1",
                        name="create_invoice_draft",
                        arguments={
                            "storeId": STORE_ID,
                            "items": [{"product": PRODUCT_ID, "quantity": 1}],
                        },
                    ),
                ],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
                prior_successful_drafts=1,
            )
        assert calls["n"] == 0  # retailer never hit
        assert results[0].success is False
        assert results[0].data["code"] == "DUPLICATE_DRAFT_CALL"

    asyncio.run(run())
