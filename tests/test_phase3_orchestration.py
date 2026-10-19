from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.confirmations.helpers import _business_key
from app.confirmations.models import PendingConfirmationRecord
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_stream import stream_chat
from app.orchestrator.model_router import ModelRouter
from app.orchestrator.tool_selector import (
    _CORE_UNKNOWN_TOOLS,
    resolve_turn_intent,
)
from app.providers.base import ModelProvider
from app.providers.openai_compatible import (
    CHEAPER_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
)
from app.schemas.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    GenerationRequest,
    GenerationResponse,
)
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)

ALL_AVAILABLE = frozenset(
    [t.name for t in READ_TOOL_DEFINITIONS]
    + [t.name for t in WRITE_TOOL_DEFINITIONS]
    + [t.name for t in SENSITIVE_TOOL_DEFINITIONS]
)


class DummyStreamingProvider(ModelProvider):
    def __init__(self, provider_name: str = "mock_stream") -> None:
        self._name = provider_name

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            message=ChatMessage(role="assistant", content="Complete text from mock"),
            finish_reason="stop",
            model=self._name,
        )

    async def generate_stream(self, request: GenerationRequest):
        chunks = ["Namaste! ", "Today's total sales ", "are ₹15,400."]
        for c in chunks:
            yield c


class DummyFailingProvider(ModelProvider):
    def __init__(self, provider_name: str = "openai") -> None:
        self._name = provider_name

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise RuntimeError("Primary provider failed")

    async def generate_stream(self, request: GenerationRequest):
        raise RuntimeError("Stream connection failed")
        yield ""


def test_unknown_intent_bounds_tool_schemas() -> None:
    intent = resolve_turn_intent(
        "tell me something random that matches no cues",
        available=ALL_AVAILABLE,
    )
    assert len(intent.tool_names) == len(_CORE_UNKNOWN_TOOLS)
    assert intent.tool_names == set(_CORE_UNKNOWN_TOOLS)
    assert "release_invoice" not in intent.tool_names
    assert "create_expense" not in intent.tool_names


@pytest.mark.parametrize(
    ("query", "expected_tool"),
    [
        ("what are today's sales", "today_sale"),
        ("aaj kitna dhandha hua", "today_sale"),
        ("aaj ki kamai batao", "today_sale"),
        ("આજનો ધંધો કેટલો થયો", "today_sale"),
        ("આજનું વેચાણ બતાવો", "today_sale"),
        ("stock kitna bacha hai", "stock_summary"),
        ("maal kitna pada hai", "stock_summary"),
        ("દુકાનમાં માલ કેટલો પડ્યો છે", "stock_summary"),
        ("જથ્થો કેટલો છે", "stock_summary"),
        ("ramesh ka khata dikhao", "get_customer_ledger"),
        ("ramesh ka udhar kitna hai", "get_customer_ledger"),
        ("ખાતું બતાવો રમેશભાઈનું", "get_customer_ledger"),
        ("ચોપડો ખોલો", "get_customer_ledger"),
        ("chai ka kharcha add karo", "create_expense"),
        ("દુકાનનો ખર્ચ ઉમેરો", "create_expense"),
        ("invoice banao bill", "create_invoice_draft"),
        ("ગ્રાહક માટે બિલ બનાવો", "create_invoice_draft"),
        ("payments kitne aaye", "payment_history"),
        ("customer ne kitna payment diya recently", "payment_history"),
        ("ચુકવણી કેટલી થઈ", "payment_history"),
        ("business overview analysis", "today_sale"),
        ("business overview analysis", "top_customers"),
    ],
)
def test_multilingual_routing_accuracy(query: str, expected_tool: str) -> None:
    intent = resolve_turn_intent(query, available=ALL_AVAILABLE)
    assert expected_tool in intent.tool_names
    assert len(intent.tool_names) < (
        len(READ_TOOL_DEFINITIONS)
        + len(WRITE_TOOL_DEFINITIONS)
        + len(SENSITIVE_TOOL_DEFINITIONS)
    )


def test_gujarati_expense_creation_sensitive_action_check() -> None:
    from app.orchestrator.tool_selector import user_requested_sensitive_action

    assert user_requested_sensitive_action("દુકાનનો ખર્ચ ઉમેરો", "create_expense")
    assert user_requested_sensitive_action("chai ka kharcha add karo", "create_expense")


def test_routing_never_exposes_writes_for_unknown() -> None:
    intent = resolve_turn_intent("random unknown intent query", available=ALL_AVAILABLE)
    write_names = {t.name for t in WRITE_TOOL_DEFINITIONS} | {
        t.name for t in SENSITIVE_TOOL_DEFINITIONS
    }
    assert not intent.tool_names.intersection(write_names)


@pytest.mark.asyncio
async def test_genuine_token_streaming_emits_deltas() -> None:
    async def mock_handle(req, **kwargs):
        emit = kwargs.get("emit")
        assert emit is not None
        await emit("assistant.delta", {"text": "Hello "})
        await emit("assistant.delta", {"text": "world!"})
        return ChatResponse(
            message="Hello world!",
            session_id=req.session_id,
            request_id="r1",
            user_id="u1",
            provider="mock_stream",
            model="mock_stream",
        )

    req = ChatRequest(text="hi", sessionId="s1", storeId="a" * 24)
    events: list[tuple[str, dict[str, Any]]] = []

    async for e in stream_chat(
        mock_handle,
        req,
        user={"sub": "u1"},
        request_id="r1",
        store_id="a" * 24,
        access_token="tok",
        metrics=None,
    ):
        events.append(e)

    event_types = [e[0] for e in events]
    assert event_types[0] == "request.started"
    assert event_types[-1] == "request.completed"

    deltas = [e[1]["text"] for e in events if e[0] == "assistant.delta"]
    assert deltas == ["Hello ", "world!"]

    completed_payload = events[-1][1]
    assert completed_payload["sessionId"] == req.session_id
    assert completed_payload["provider"] == "mock_stream"


@pytest.mark.asyncio
async def test_ai_gateway_generate_stream_yields_tokens() -> None:
    router = ModelRouter()
    provider = DummyStreamingProvider("mock_stream")
    router.register(provider)
    router.set_active("mock_stream")

    gateway = AiGateway(model_router=router)
    req = GenerationRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="mock_stream",
    )

    tokens: list[str] = []
    async for chunk in gateway.generate_stream(req):
        tokens.append(chunk)

    assert tokens == ["Namaste! ", "Today's total sales ", "are ₹15,400."]


@pytest.mark.asyncio
async def test_ai_gateway_stream_fallback_before_emission() -> None:
    router = ModelRouter()
    failing = DummyFailingProvider(OPENAI_PROVIDER_NAME)
    fallback = DummyStreamingProvider(CHEAPER_PROVIDER_NAME)
    router.register(failing)
    router.register(fallback)
    router.set_active(OPENAI_PROVIDER_NAME)

    gateway = AiGateway(model_router=router)
    req = GenerationRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-4o",
    )

    tokens: list[str] = []
    async for chunk in gateway.generate_stream(req):
        tokens.append(chunk)

    assert tokens == ["Namaste! ", "Today's total sales ", "are ₹15,400."]


@pytest.mark.asyncio
async def test_stream_cancellation_safely_terminates() -> None:
    async def infinite_handle(req, **kwargs):
        emit = kwargs.get("emit")
        while True:
            await emit("assistant.delta", {"text": "tick "})
            await asyncio.sleep(0.01)

    req = ChatRequest(text="hi", sessionId="s1", storeId="a" * 24)
    received = []

    async for e in stream_chat(
        infinite_handle,
        req,
        user={"sub": "u1"},
        request_id="r_cancel",
        store_id="a" * 24,
        access_token="tok",
        metrics=None,
    ):
        received.append(e)
        if len(received) >= 2:
            break

    assert len(received) >= 2


def test_idempotency_key_scoping_in_confirmations() -> None:
    rec1 = PendingConfirmationRecord(
        confirmation_id="conf-001",
        user_id="user_1",
        store_id="a" * 24,
        session_id="sess_1",
        type="expense",
        draft_id="",
        summary={"action": "create_expense"},
        tool_name="create_expense",
        arguments={"amount": 100, "category": "chai"},
        expires_at=9999999999.0,
        status="PENDING",
    )
    rec2 = PendingConfirmationRecord(
        confirmation_id="conf-002",
        user_id="user_1",
        store_id="a" * 24,
        session_id="sess_1",
        type="expense",
        draft_id="",
        summary={"action": "create_expense"},
        tool_name="create_expense",
        arguments={"amount": 100, "category": "chai"},
        expires_at=9999999999.0,
        status="PENDING",
    )

    k1 = _business_key(rec1)
    k2 = _business_key(rec2)
    k1_retry = _business_key(rec1)

    assert k1 != k2
    assert k1 == k1_retry


class DummyMidStreamFailingProvider(ModelProvider):
    def __init__(self, provider_name: str = OPENAI_PROVIDER_NAME) -> None:
        self._name = provider_name

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise RuntimeError("Generation failed")

    async def generate_stream(self, request: GenerationRequest):
        yield "Initial chunk "
        raise RuntimeError("Mid-stream connection broke")


@pytest.mark.asyncio
async def test_mid_stream_failure_does_not_fallback() -> None:
    router = ModelRouter()
    failing = DummyMidStreamFailingProvider(OPENAI_PROVIDER_NAME)
    fallback = DummyStreamingProvider(CHEAPER_PROVIDER_NAME)
    router.register(failing)
    router.register(fallback)
    router.set_active(OPENAI_PROVIDER_NAME)

    gateway = AiGateway(model_router=router)
    req = GenerationRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-4o",
    )

    yielded = []
    with pytest.raises(RuntimeError, match="Mid-stream connection broke"):
        async for chunk in gateway.generate_stream(req):
            yielded.append(chunk)

    assert yielded == ["Initial chunk "]


@pytest.mark.asyncio
async def test_stream_worker_failure_aborts_cleanly() -> None:
    async def failing_handle(req, **kwargs):
        emit = kwargs.get("emit")
        assert emit is not None
        await emit("assistant.delta", {"text": "Partial text "})
        raise RuntimeError("Provider died mid-stream")

    req = ChatRequest(text="hi", sessionId="s1", storeId="a" * 24)
    events: list[tuple[str, dict[str, Any]]] = []

    async for e in stream_chat(
        failing_handle,
        req,
        user={"sub": "u1"},
        request_id="r_fail",
        store_id="a" * 24,
        access_token="tok",
        metrics=None,
    ):
        events.append(e)

    event_types = [e[0] for e in events]
    assert "assistant.delta" in event_types
    assert event_types[-1] == "request.aborted"
