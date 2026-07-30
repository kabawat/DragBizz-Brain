"""API-level tests for POST /api/v1/chat/confirm."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.confirmations import (
    CONFIRMATION_TYPE_INVOICE_RELEASE,
    InMemoryConfirmationStore,
)
from app.main import create_app
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import GenerationRequest, GenerationResponse
from tests.conftest import StaticPemVerifier, make_access_token

STORE_ID = "507f1f77bcf86cd799439011"
INVOICE_ID = "807f1f77bcf86cd799439011"
SESSION_ID = "api-confirm-session"


class FakeProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider=self.name,
            model="fake-model",
            content="ok",
            tool_calls=[],
        )


def _install(app: Any, confirmation_store: InMemoryConfirmationStore) -> None:
    router = ModelRouter()
    provider = FakeProvider()
    router.register(provider)
    router.set_active(provider.name)
    gateway = AiGateway(router)
    app.state.model_router = router
    app.state.ai_gateway = gateway
    app.state.confirmation_store = confirmation_store
    app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=app.state.tool_registry,
        settings=get_settings(),
        tool_executor=app.state.tool_executor,
        confirmation_store=confirmation_store,
    )


def test_confirm_requires_auth(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    with TestClient(create_app()) as client:
        _install(client.app, InMemoryConfirmationStore())
        response = client.post(
            "/api/v1/chat/confirm",
            json={
                "sessionId": SESSION_ID,
                "storeId": STORE_ID,
                "confirmationId": "x",
                "draftId": INVOICE_ID,
                "action": "approve",
            },
        )
    assert response.status_code == 401


def test_confirm_reject_happy_path(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    store = InMemoryConfirmationStore()
    record = asyncio.run(
        store.create(
            user_id="user-1",
            store_id=STORE_ID,
            session_id=SESSION_ID,
            type=CONFIRMATION_TYPE_INVOICE_RELEASE,
            draft_id=INVOICE_ID,
            summary={"total": 10},
            tool_name="release_invoice",
            arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
        )
    )
    token = make_access_token(rsa_keypair["private_pem"], sub="user-1")
    with TestClient(create_app()) as client:
        _install(client.app, store)
        response = client.post(
            "/api/v1/chat/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "sessionId": SESSION_ID,
                "storeId": STORE_ID,
                "confirmationId": record.confirmation_id,
                "draftId": INVOICE_ID,
                "action": "reject",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert "cancel" in body["message"].lower()
    assert body.get("pendingConfirmation") is None


def test_confirm_expired(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    clock = {"now": 1_000.0}
    store = InMemoryConfirmationStore(ttl_seconds=1, clock=lambda: clock["now"])
    record = asyncio.run(
        store.create(
            user_id="user-1",
            store_id=STORE_ID,
            session_id=SESSION_ID,
            type=CONFIRMATION_TYPE_INVOICE_RELEASE,
            draft_id=INVOICE_ID,
            summary={},
            tool_name="release_invoice",
            arguments={"storeId": STORE_ID, "invoiceId": INVOICE_ID},
        )
    )
    clock["now"] = 1_010.0
    token = make_access_token(rsa_keypair["private_pem"], sub="user-1")
    with TestClient(create_app()) as client:
        _install(client.app, store)
        response = client.post(
            "/api/v1/chat/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "sessionId": SESSION_ID,
                "storeId": STORE_ID,
                "confirmationId": record.confirmation_id,
                "draftId": INVOICE_ID,
                "action": "approve",
            },
        )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "CONFIRMATION_EXPIRED"
