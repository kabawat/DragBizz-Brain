"""Phase 1: sensitive khata writes stage, then confirm once."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.confirmations import InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerResponse
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import stage_from_sensitive_calls
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.orchestrator.tool_loop import run_tool_loop
from app.orchestrator.tool_selector import user_requested_sensitive_action
from app.schemas.chat import ChatMessage, ConfirmRequest, GenerationResponse
from app.schemas.tool import ToolCall
from app.sessions import InMemorySessionStore
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE = "a" * 24
OTHER_STORE = "d" * 24
CUSTOMER = "b" * 24
INVOICE = "c" * 24
SESSION = "sess-1"


class RecordingRetailer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def create_ledger_transaction(self, **kwargs):
        self.calls.append(("ledger", kwargs))
        return RetailerResponse(status_code=200, body={"data": {"id": "tx1"}})

    async def release_invoice(self, **kwargs):
        self.calls.append(("release", kwargs))
        return RetailerResponse(
            status_code=200,
            body={"data": {"invoice": {"id": kwargs["invoice_id"]}}},
        )

    async def get_products(self, **kwargs):
        self.calls.append(("products", kwargs))
        return RetailerResponse(status_code=200, body={"data": []})


class Gateway:
    async def continue_or_synthesize(self, *_args, **_kwargs):
        return GenerationResponse(
            provider="test", model="m", content="done", tool_calls=[]
        )

    async def repair_tool_calls(self, *_args, **_kwargs):
        raise AssertionError("tool call should already be valid")


def _settings():
    return SimpleNamespace(
        chat=SimpleNamespace(
            max_tool_rounds=3,
            temperature=0.0,
            max_tokens=32,
            synthesis_max_tokens=32,
        )
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    groups = (
        (READ_TOOL_DEFINITIONS, READ_TOOL_HANDLERS),
        (WRITE_TOOL_DEFINITIONS, WRITE_TOOL_HANDLERS),
        (SENSITIVE_TOOL_DEFINITIONS, SENSITIVE_TOOL_HANDLERS),
    )
    for definitions, handlers in groups:
        for definition in definitions:
            registry.register(definition, handlers[definition.name])
    return registry


def _generation(call: ToolCall) -> GenerationResponse:
    return GenerationResponse(
        provider="test",
        model="m",
        content="",
        tool_calls=[call],
    )


async def _run(question: str, call: ToolCall, retailer: RecordingRetailer):
    registry = _registry()
    executor = ToolExecutor(registry=registry, retailer=retailer)
    return await run_tool_loop(
        gateway=Gateway(),
        validator=ToolCallValidator(registry),
        registry=registry,
        executor=executor,
        confirmations=InMemoryConfirmationStore(),
        settings=_settings(),
        generation=_generation(call),
        messages=[ChatMessage(role="user", content=question)],
        tools=list(registry.definitions()),
        language="hi-IN",
        store_id=STORE,
        access_token="token",
        session_id=SESSION,
        user_id="user-1",
    ), executor


def _guard(message: str, **_kwargs) -> str:
    return message


def test_sensitive_cues_require_the_user_to_ask() -> None:
    assert user_requested_sensitive_action("jama karo 500", "ledger_credit")
    assert user_requested_sensitive_action("udhaar dalo 200", "ledger_debit")
    assert user_requested_sensitive_action("release the draft", "release_invoice")
    assert not user_requested_sensitive_action(
        "maggi current price", "ledger_debit"
    )


def test_ledger_confirm_posts_once() -> None:
    asyncio.run(_confirm_staged())


async def _confirm_staged() -> None:
    retailer = RecordingRetailer()
    registry = _registry()
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(registry=registry, retailer=retailer)
    call = ToolCall(
        id="call-credit",
        name="ledger_credit",
        arguments={
            "storeId": STORE,
            "customerId": CUSTOMER,
            "amount": 500,
        },
    )
    outcome = await run_tool_loop(
        gateway=Gateway(),
        validator=ToolCallValidator(registry),
        registry=registry,
        executor=executor,
        confirmations=confirmations,
        settings=_settings(),
        generation=_generation(call),
        messages=[ChatMessage(role="user", content="jama karo 500")],
        tools=list(registry.definitions()),
        language="hi-IN",
        store_id=STORE,
        access_token="token",
        session_id=SESSION,
        user_id="user-1",
    )
    staged = outcome.staged_sensitive
    assert staged is not None
    assert staged.type == "ledger_credit"
    assert staged.draft_id == CUSTOMER
    assert staged.arguments["storeId"] == STORE
    assert staged.summary["action"] == "payment"
    assert retailer.calls == []

    body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId=staged.confirmation_id,
        draftId=CUSTOMER,
        action="approve",
    )
    response = await handle_confirm(
        body,
        user_id="user-1",
        request_id="req-1",
        store_id=STORE,
        access_token="token",
        confirmations=confirmations,
        sessions=InMemorySessionStore(),
        executor=executor,
        guard_output=_guard,
    )
    assert len(retailer.calls) == 1
    kind, kwargs = retailer.calls[0]
    assert kind == "ledger"
    assert kwargs["store_id"] == STORE
    assert kwargs["customer_id"] == CUSTOMER
    assert kwargs["idempotency_key"]
    assert response.message == "Payment of ₹500 recorded on the customer khata."

    with pytest.raises(AppError) as caught:
        await handle_confirm(
            body,
            user_id="user-1",
            request_id="req-2",
            store_id=STORE,
            access_token="token",
            confirmations=confirmations,
            sessions=InMemorySessionStore(),
            executor=executor,
            guard_output=_guard,
        )
    assert caught.value.status_code == 409
    assert len(retailer.calls) == 1


def test_ledger_reject_does_not_call_retailer() -> None:
    asyncio.run(_reject_ledger())


async def _reject_ledger() -> None:
    retailer = RecordingRetailer()
    registry = _registry()
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(registry=registry, retailer=retailer)
    call = ToolCall(
        id="call-debit",
        name="ledger_debit",
        arguments={
            "storeId": STORE,
            "customerId": CUSTOMER,
            "amount": 80,
        },
    )
    outcome = await run_tool_loop(
        gateway=Gateway(),
        validator=ToolCallValidator(registry),
        registry=registry,
        executor=executor,
        confirmations=confirmations,
        settings=_settings(),
        generation=_generation(call),
        messages=[ChatMessage(role="user", content="udhaar dalo 80")],
        tools=list(registry.definitions()),
        language="hi-IN",
        store_id=STORE,
        access_token="token",
        session_id=SESSION,
        user_id="user-1",
    )
    staged = outcome.staged_sensitive
    assert staged is not None
    response = await handle_confirm(
        ConfirmRequest(
            sessionId=SESSION,
            storeId=STORE,
            confirmationId=staged.confirmation_id,
            draftId=CUSTOMER,
            action="reject",
        ),
        user_id="user-1",
        request_id="req-1",
        store_id=STORE,
        access_token="token",
        confirmations=confirmations,
        sessions=InMemorySessionStore(),
        executor=executor,
        guard_output=_guard,
    )
    assert retailer.calls == []
    assert "cancelled" in response.message.lower()


def test_store_mismatch_never_calls_retailer() -> None:
    asyncio.run(_store_mismatch())


async def _store_mismatch() -> None:
    retailer = RecordingRetailer()
    executor = ToolExecutor(registry=_registry(), retailer=retailer)
    call = ToolCall(
        id="call-search",
        name="search_product",
        arguments={"storeId": OTHER_STORE, "query": "maggi"},
    )
    with pytest.raises(AppError) as caught:
        await executor.execute_reads(
            [call],
            access_token="token",
            store_id=STORE,
            allowed_names=frozenset({"search_product"}),
        )
    assert caught.value.code == "TOOL_ARGS_INVALID"
    assert retailer.calls == []


def test_uncued_sensitive_call_is_not_staged() -> None:
    asyncio.run(_uncued())


async def _uncued() -> None:
    retailer = RecordingRetailer()
    call = ToolCall(
        id="call-debit",
        name="ledger_debit",
        arguments={
            "storeId": STORE,
            "customerId": CUSTOMER,
            "amount": 999,
        },
    )
    outcome, _executor = await _run("maggi current price", call, retailer)
    assert outcome.staged_sensitive is None
    assert retailer.calls == []
    assert outcome.all_results[0].success is False
    assert outcome.all_results[0].data["code"] == "SENSITIVE_NOT_REQUESTED"


def test_release_invoice_still_stages_without_posting() -> None:
    asyncio.run(_release_stages())


async def _release_stages() -> None:
    retailer = RecordingRetailer()
    call = ToolCall(
        id="call-release",
        name="release_invoice",
        arguments={"storeId": STORE, "invoiceId": INVOICE},
    )
    outcome, _executor = await _run("release the draft", call, retailer)
    staged = outcome.staged_sensitive
    assert staged is not None
    assert staged.type == "invoice_release"
    assert staged.tool_name == "release_invoice"
    assert staged.draft_id == INVOICE
    assert retailer.calls == []


def test_stage_overwrites_model_store_id() -> None:
    asyncio.run(_stage_store())


async def _stage_store() -> None:
    call = ToolCall(
        id="call-credit",
        name="ledger_credit",
        arguments={
            "storeId": OTHER_STORE,
            "customerId": CUSTOMER,
            "amount": 10,
        },
    )
    record = await stage_from_sensitive_calls(
        InMemoryConfirmationStore(),
        user_id="user-1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[call],
    )
    assert record is not None
    assert record.arguments["storeId"] == STORE
