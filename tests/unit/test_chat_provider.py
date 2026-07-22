from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerClient
from app.main import create_app
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall
from tests.conftest import StaticPemVerifier, make_access_token

STORE_ID = "507f1f77bcf86cd799439011"


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


def _retailer_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/analytics/revenue"):
        return httpx.Response(
            200,
            json={
                "data": {
                    "today": {"revenue": 500, "profit": 100, "sales": 3}
                }
            },
        )
    if path.endswith("/product"):
        return httpx.Response(
            200,
            json={
                "data": [{"id": "p1", "name": "Atta"}],
                "pagination": {"limit": 20, "total": 1},
            },
        )
    if path.endswith("/analytics/stock"):
        return httpx.Response(
            200,
            json={"data": {"totals": {"totalSkus": 10}}},
        )
    if path.endswith("/customer-account/payments"):
        return httpx.Response(200, json={"data": [], "pagination": {}})
    return httpx.Response(404, json={"message": "not found"})


def _wire_chat(
    app: Any,
    provider: ModelProvider,
    retailer_handler=_retailer_handler,
) -> httpx.AsyncClient:
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    gateway = AiGateway(router)

    transport = httpx.MockTransport(retailer_handler)
    http_client = httpx.AsyncClient(
        transport=transport, base_url="http://retailer.test"
    )
    retailer = RetailerClient(http_client, "http://retailer.test")
    executor = ToolExecutor(
        registry=app.state.tool_registry, retailer=retailer
    )
    app.state.model_router = router
    app.state.ai_gateway = gateway
    app.state.retailer_client = retailer
    app.state.tool_executor = executor
    app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=app.state.tool_registry,
        settings=get_settings(),
        tool_executor=executor,
    )
    return http_client


def _auth_client(
    monkeypatch: Any,
    rsa_keypair: dict[str, Any],
    provider: ModelProvider,
    retailer_handler=_retailer_handler,
) -> tuple[TestClient, httpx.AsyncClient]:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    client = TestClient(create_app())
    client.__enter__()
    mock_http = _wire_chat(client.app, provider, retailer_handler)
    return client, mock_http


def test_chat_returns_tool_calls_and_results(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
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
                        arguments={"storeId": STORE_ID},
                    )
                ],
            )
        ]
    )
    client, mock_http = _auth_client(monkeypatch, rsa_keypair, provider)
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Aaj ki sale?",
                "sessionId": "s1",
                "storeId": STORE_ID,
            },
        )
    finally:
        client.__exit__(None, None, None)
        mock_http._transport = None  # noqa: SLF001

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "scripted"
    assert payload["toolCalls"][0]["name"] == "today_sale"
    assert payload["toolResults"] == [
        {
            "tool": "today_sale",
            "success": True,
            "data": {"revenue": 500, "profit": 100, "sales": 3},
        }
    ]
    assert provider.calls == 1


def test_chat_tool_forbidden_in_results(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "No permission"})

    provider = ScriptedProvider(
        [
            GenerationResponse(
                provider="scripted",
                model="m1",
                content="Checking stock.",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="stock_summary",
                        arguments={"storeId": STORE_ID},
                    )
                ],
            )
        ]
    )
    client, mock_http = _auth_client(
        monkeypatch, rsa_keypair, provider, forbidden
    )
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Stock?",
                "sessionId": "s1",
                "storeId": STORE_ID,
            },
        )
    finally:
        client.__exit__(None, None, None)
        mock_http._transport = None  # noqa: SLF001

    assert response.status_code == 200
    assert response.json()["toolResults"][0] == {
        "tool": "stock_summary",
        "success": False,
        "data": {"code": "TOOL_FORBIDDEN", "message": "No permission"},
    }


def test_chat_tool_unauthorized(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    provider = ScriptedProvider(
        [
            GenerationResponse(
                provider="scripted",
                model="m1",
                content="Sale",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="today_sale",
                        arguments={"storeId": STORE_ID},
                    )
                ],
            )
        ]
    )
    client, mock_http = _auth_client(
        monkeypatch, rsa_keypair, provider, unauthorized
    )
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Sale?",
                "sessionId": "s1",
                "storeId": STORE_ID,
            },
        )
    finally:
        client.__exit__(None, None, None)
        mock_http._transport = None  # noqa: SLF001

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOOL_UNAUTHORIZED"


def test_chat_repairs_invalid_tool_args_once(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
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
                        arguments={"storeId": STORE_ID},
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
                        arguments={"storeId": STORE_ID, "query": "atta"},
                    )
                ],
            ),
        ]
    )
    client, mock_http = _auth_client(monkeypatch, rsa_keypair, provider)
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Find atta",
                "sessionId": "s1",
                "storeId": STORE_ID,
            },
        )
    finally:
        client.__exit__(None, None, None)
        mock_http._transport = None  # noqa: SLF001

    assert response.status_code == 200
    assert response.json()["toolCalls"][0]["arguments"]["query"] == "atta"
    assert response.json()["toolResults"][0]["success"] is True
    assert provider.calls == 2


def test_chat_fails_after_failed_repair(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    bad = GenerationResponse(
        provider="scripted",
        model="m1",
        content="",
        tool_calls=[
            ToolCall(
                id="bad",
                name="search_product",
                arguments={"storeId": STORE_ID},
            )
        ],
    )
    provider = ScriptedProvider([bad, bad])
    client, mock_http = _auth_client(monkeypatch, rsa_keypair, provider)
    try:
        token = make_access_token(rsa_keypair["private_pem"])
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Find atta",
                "sessionId": "s1",
                "storeId": STORE_ID,
            },
        )
    finally:
        client.__exit__(None, None, None)
        mock_http._transport = None  # noqa: SLF001

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
                "storeId": STORE_ID,
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"
