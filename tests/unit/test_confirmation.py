"""Phase 5 — confirmation store, release staging, confirm approve/reject."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import Settings
from app.confirmations import (
    CONFIRMATION_TYPE_INVOICE_RELEASE,
    InMemoryConfirmationStore,
)
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.idempotency import InMemoryIdempotencyStore
from app.integrations.retailer_client import RetailerClient
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.confirmation import (
    extract_invoice_id,
    stage_from_draft_result,
)
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    GenerationRequest,
    GenerationResponse,
)
from app.schemas.tool import ToolCall, ToolResult
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"
INVOICE_ID = "807f1f77bcf86cd799439011"
SESSION_ID = "session-confirm-1"
USER_ID = "user-1"


# -------------------------------------------------------------- store


def test_confirmation_store_ttl_and_consume() -> None:
    clock = {"now": 1_000.0}
    store = InMemoryConfirmationStore(ttl_seconds=10, clock=lambda: clock["now"])
    record = store.create(
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=INVOICE_ID,
        summary={"total": 85, "currency": "INR"},
        tool_name="release_invoice",
        arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
    )
    assert record.confirmation_id
    public = record.to_public()
    assert public["type"] == "invoice_release"
    assert public["draftId"] == INVOICE_ID
    assert public["expiresAt"].endswith("Z")

    got = store.get(
        record.confirmation_id,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
    )
    assert got.draft_id == INVOICE_ID

    consumed = store.consume(
        record.confirmation_id,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        draft_id=INVOICE_ID,
    )
    assert consumed.draft_id == INVOICE_ID

    with pytest.raises(AppError) as exc:
        store.consume(
            record.confirmation_id,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
            draft_id=INVOICE_ID,
        )
    assert exc.value.code == "CONFIRMATION_REQUIRED"


def test_confirmation_store_expired() -> None:
    clock = {"now": 1_000.0}
    store = InMemoryConfirmationStore(ttl_seconds=5, clock=lambda: clock["now"])
    record = store.create(
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=INVOICE_ID,
        summary={},
        tool_name="release_invoice",
        arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
    )
    clock["now"] = 1_010.0
    with pytest.raises(AppError) as exc:
        store.get(
            record.confirmation_id,
            user_id=USER_ID,
            store_id=STORE_ID,
            session_id=SESSION_ID,
        )
    assert exc.value.code == "CONFIRMATION_EXPIRED"


def test_confirmation_store_forbidden_owner() -> None:
    store = InMemoryConfirmationStore(ttl_seconds=300)
    record = store.create(
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=INVOICE_ID,
        summary={},
        tool_name="release_invoice",
        arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
    )
    with pytest.raises(AppError) as exc:
        store.get(
            record.confirmation_id,
            user_id="other-user",
            store_id=STORE_ID,
            session_id=SESSION_ID,
        )
    assert exc.value.code == "CONFIRMATION_FORBIDDEN"


def test_extract_invoice_id_from_nested_payload() -> None:
    assert extract_invoice_id({"invoice": {"id": INVOICE_ID}}) == INVOICE_ID
    assert extract_invoice_id({"id": INVOICE_ID}) == INVOICE_ID


def test_stage_from_draft_result() -> None:
    store = InMemoryConfirmationStore(ttl_seconds=300)
    result = ToolResult(
        tool="create_invoice_draft",
        success=True,
        data={
            "invoice": {"id": INVOICE_ID, "totalAmount": 120},
            "openPath": f"/dashboard/invoices/{INVOICE_ID}",
        },
    )
    record = stage_from_draft_result(
        store,
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        result=result,
    )
    assert record is not None
    assert record.type == CONFIRMATION_TYPE_INVOICE_RELEASE
    assert record.draft_id == INVOICE_ID
    assert record.summary["total"] == 120


# -------------------------------------------------------------- retailer + executor


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register(definition, READ_TOOL_HANDLERS[definition.name])
    for definition in WRITE_TOOL_DEFINITIONS:
        registry.register(definition, WRITE_TOOL_HANDLERS[definition.name])
    for definition in SENSITIVE_TOOL_DEFINITIONS:
        registry.register(definition, SENSITIVE_TOOL_HANDLERS[definition.name])
    return registry


def test_release_invoice_posts_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["store"] = request.url.params.get("store")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": INVOICE_ID,
                    "invoiceStatus": "RELEASED",
                }
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            result = await retailer.release_invoice(
                access_token="token",
                store_id=STORE_ID,
                invoice_id=INVOICE_ID,
            )
        assert result.status_code == 200

    asyncio.run(run())
    assert seen["method"] == "POST"
    assert seen["path"] == "/invoices/release"
    assert seen["store"] == STORE_ID
    assert seen["body"]["id"] == INVOICE_ID


def test_execute_confirmations_releases_once_idempotent() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "invoice": {"id": INVOICE_ID},
                    "alreadyReleased": calls["n"] > 1,
                }
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(
                registry=_full_registry(),
                retailer=retailer,
                idempotency_store=InMemoryIdempotencyStore(),
            )
            call = ToolCall(
                id="c1",
                name="release_invoice",
                arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
            )
            first = await executor.execute_confirmations(
                [call],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
                confirmation_id="conf-1",
            )
            second = await executor.execute_confirmations(
                [call],
                access_token="token",
                store_id=STORE_ID,
                session_id=SESSION_ID,
                user_id=USER_ID,
                confirmation_id="conf-1",
            )
            assert first[0].success is True
            assert second[0].success is True
            assert calls["n"] == 1  # second hit idempotency cache

    asyncio.run(run())


def test_sensitive_not_auto_executable_via_writes() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, json={"message": "should not call"})
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(
                registry=_full_registry(),
                retailer=retailer,
            )
            with pytest.raises(AppError) as exc:
                await executor.execute_writes(
                    [
                        ToolCall(
                            id="c1",
                            name="release_invoice",
                            arguments={
                                "storeId": STORE_ID,
                                "invoiceId": INVOICE_ID,
                            },
                        )
                    ],
                    access_token="token",
                    store_id=STORE_ID,
                    session_id=SESSION_ID,
                    user_id=USER_ID,
                )
            assert exc.value.code == "TOOL_NOT_EXECUTABLE"

    asyncio.run(run())


# -------------------------------------------------------------- ChatService


class ScriptedProvider(ModelProvider):
    def __init__(self, responses: list[GenerationResponse]) -> None:
        self._responses = list(responses)

    @property
    def name(self) -> str:
        return "scripted"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return self._responses.pop(0)


def _chat_service(
    provider: ModelProvider,
    *,
    confirmation_store: InMemoryConfirmationStore | None = None,
    executor: ToolExecutor | None = None,
) -> ChatService:
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = _full_registry()
    if executor is None:
        executor = MagicMock(spec=ToolExecutor)
        executor.execute_reads = AsyncMock(return_value=[])
        executor.execute_writes = AsyncMock(return_value=[])
        executor.execute_confirmations = AsyncMock(return_value=[])
    return ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(
            environment="test",
            input_guard_mode="off",
            output_guard_mode="off",
            confirmation_ttl_seconds=300,
        ),
        tool_executor=executor,
        confirmation_store=confirmation_store or InMemoryConfirmationStore(),
    )


def test_chat_stages_pending_on_sensitive_release_without_retailer() -> None:
    provider = ScriptedProvider(
        [
            GenerationResponse(
                provider="scripted",
                model="m",
                content="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="release_invoice",
                        arguments={
                            "storeId": STORE_ID,
                            "invoiceId": INVOICE_ID,
                        },
                    )
                ],
            ),
            GenerationResponse(
                provider="scripted",
                model="m",
                content="Confirm to release the draft invoice.",
            ),
        ]
    )
    confirmations = InMemoryConfirmationStore()
    retailer_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        retailer_calls["n"] += 1
        return httpx.Response(500, json={"message": "nope"})

    async def run() -> ChatResponse:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(
                registry=_full_registry(),
                retailer=retailer,
            )
            service = _chat_service(
                provider,
                confirmation_store=confirmations,
                executor=executor,
            )
            return await service.handle(
                ChatRequest(
                    text="Release the draft",
                    sessionId=SESSION_ID,
                    storeId=STORE_ID,
                    language="en-IN",
                ),
                user={"sub": USER_ID},
                request_id="r1",
                store_id=STORE_ID,
                access_token="token",
            )

    response = asyncio.run(run())
    assert retailer_calls["n"] == 0
    assert response.pending_confirmation is not None
    assert response.pending_confirmation.draft_id == INVOICE_ID
    assert response.pending_confirmation.type == "invoice_release"
    assert response.tool_results[0].data["status"] == "pending_confirmation"


def test_chat_stages_pending_after_draft_write() -> None:
    provider = ScriptedProvider(
        [
            GenerationResponse(
                provider="scripted",
                model="m",
                content="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="create_invoice_draft",
                        arguments={
                            "storeId": STORE_ID,
                            "items": [
                                {
                                    "product": "707f1f77bcf86cd799439011",
                                    "quantity": 1,
                                }
                            ],
                        },
                    )
                ],
            ),
            GenerationResponse(
                provider="scripted",
                model="m",
                content="Draft ready — confirm to release.",
            ),
        ]
    )
    confirmations = InMemoryConfirmationStore()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "data": {
                    "invoice": {"id": INVOICE_ID, "totalAmount": 99},
                }
            },
        )

    async def run() -> Any:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(
                registry=_full_registry(),
                retailer=retailer,
                idempotency_store=InMemoryIdempotencyStore(),
            )
            service = _chat_service(
                provider,
                confirmation_store=confirmations,
                executor=executor,
            )
            return await service.handle(
                ChatRequest(
                    text="Make a bill",
                    sessionId=SESSION_ID,
                    storeId=STORE_ID,
                    language="en-IN",
                ),
                user={"sub": USER_ID},
                request_id="r1",
                store_id=STORE_ID,
                access_token="token",
            )

    response = asyncio.run(run())
    assert response.pending_confirmation is not None
    assert response.pending_confirmation.draft_id == INVOICE_ID
    assert response.pending_confirmation.summary.get("total") == 99


def test_confirm_approve_releases_and_reject_skips_retailer() -> None:
    confirmations = InMemoryConfirmationStore()
    record = confirmations.create(
        user_id=USER_ID,
        store_id=STORE_ID,
        session_id=SESSION_ID,
        type=CONFIRMATION_TYPE_INVOICE_RELEASE,
        draft_id=INVOICE_ID,
        summary={"total": 50, "currency": "INR"},
        tool_name="release_invoice",
        arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"data": {"invoice": {"id": INVOICE_ID}}},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://retailer.test"
        ) as client:
            retailer = RetailerClient(client, "http://retailer.test")
            executor = ToolExecutor(
                registry=_full_registry(),
                retailer=retailer,
                idempotency_store=InMemoryIdempotencyStore(),
            )
            service = _chat_service(
                ScriptedProvider([]),
                confirmation_store=confirmations,
                executor=executor,
            )
            approved = await service.confirm(
                ConfirmRequest(
                    sessionId=SESSION_ID,
                    storeId=STORE_ID,
                    confirmationId=record.confirmation_id,
                    draftId=INVOICE_ID,
                    action="approve",
                ),
                user={"sub": USER_ID},
                request_id="r-approve",
                store_id=STORE_ID,
                access_token="token",
            )
            assert "released" in approved.message.lower()
            assert calls["n"] == 1

            # Fresh pending for reject path
            pending = confirmations.create(
                user_id=USER_ID,
                store_id=STORE_ID,
                session_id=SESSION_ID,
                type=CONFIRMATION_TYPE_INVOICE_RELEASE,
                draft_id=INVOICE_ID,
                summary={},
                tool_name="release_invoice",
                arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
            )
            rejected = await service.confirm(
                ConfirmRequest(
                    sessionId=SESSION_ID,
                    storeId=STORE_ID,
                    confirmationId=pending.confirmation_id,
                    draftId=INVOICE_ID,
                    action="reject",
                ),
                user={"sub": USER_ID},
                request_id="r-reject",
                store_id=STORE_ID,
                access_token="token",
            )
            assert "cancel" in rejected.message.lower()
            assert calls["n"] == 1  # reject did not call retailer

    asyncio.run(run())


def test_confirm_without_pending_rejected() -> None:
    service = _chat_service(ScriptedProvider([]))

    async def run() -> None:
        with pytest.raises(AppError) as exc:
            await service.confirm(
                ConfirmRequest(
                    sessionId=SESSION_ID,
                    storeId=STORE_ID,
                    confirmationId="missing-id",
                    draftId=INVOICE_ID,
                    action="approve",
                ),
                user={"sub": USER_ID},
                request_id="r1",
                store_id=STORE_ID,
                access_token="token",
            )
        assert exc.value.code == "CONFIRMATION_NOT_FOUND"

    asyncio.run(run())
