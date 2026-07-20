from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.exceptions import AppError
from app.main import create_app
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall
from tests.conftest import StaticPemVerifier, make_access_token


class ScriptedProvider(ModelProvider):
    def __init__(self, responses: list[GenerationResponse | AppError]) -> None:
        self._responses = list(responses)
        self.calls = 0

    @property
    def name(self) -> str:
        return "scripted"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, AppError):
            raise item
        return item


def _auth_client(
    monkeypatch: Any,
    rsa_keypair: dict[str, Any],
    provider: ModelProvider,
) -> TestClient:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    client = TestClient(create_app())
    client.__enter__()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    gateway = AiGateway(router)
    client.app.state.model_router = router
    client.app.state.ai_gateway = gateway
    client.app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=client.app.state.tool_registry,
        settings=get_settings(),
    )
    return client


def test_chat_returns_tool_calls(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    store_id = "507f1f77bcf86cd799439011"
    provider = ScriptedProvider(
        [
            GenerationResponse(
                provider="scripted",
                model="m1",
                content="Fetching today's sale.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="today_sale",
                        arguments={"storeId": store_id},
                    )
                ],
            )
        ]
    )
    client = _auth_client(monkeypatch, rsa_keypair, provider)
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Aaj ki sale?",
                "sessionId": "s1",
                "storeId": store_id,
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "scripted"
    assert payload["toolCalls"] == [
        {
            "id": "call_1",
            "name": "today_sale",
            "arguments": {"storeId": store_id},
        }
    ]
    assert provider.calls == 1


def test_chat_repairs_invalid_tool_args_once(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    store_id = "507f1f77bcf86cd799439011"
    provider = ScriptedProvider(
        [
            GenerationResponse(
                provider="scripted",
                model="m1",
                content="",
                tool_calls=[
                    ToolCall(
                        id="bad",
                        name="search_product",
                        arguments={"storeId": store_id},
                    )
                ],
            ),
            GenerationResponse(
                provider="scripted",
                model="m1",
                content="Searching.",
                tool_calls=[
                    ToolCall(
                        id="good",
                        name="search_product",
                        arguments={"storeId": store_id, "query": "atta"},
                    )
                ],
            ),
        ]
    )
    client = _auth_client(monkeypatch, rsa_keypair, provider)
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Find atta",
                "sessionId": "s1",
                "storeId": store_id,
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    assert response.json()["toolCalls"][0]["arguments"]["query"] == "atta"
    assert provider.calls == 2


def test_chat_fails_after_failed_repair(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    store_id = "507f1f77bcf86cd799439011"
    bad = GenerationResponse(
        provider="scripted",
        model="m1",
        content="",
        tool_calls=[
            ToolCall(
                id="bad",
                name="search_product",
                arguments={"storeId": store_id},
            )
        ],
    )
    provider = ScriptedProvider([bad, bad])
    client = _auth_client(monkeypatch, rsa_keypair, provider)
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Find atta",
                "sessionId": "s1",
                "storeId": store_id,
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TOOL_ARGS_INVALID"
    assert provider.calls == 2


def test_chat_provider_not_configured(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    with TestClient(create_app()) as client:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "hello",
                "sessionId": "s1",
                "storeId": "507f1f77bcf86cd799439011",
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"
