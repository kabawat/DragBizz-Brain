from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.integrations.auth_jwks import normalize_access_claims
from app.main import create_app
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import GenerationRequest, GenerationResponse
from tests.conftest import StaticPemVerifier, make_access_token


class FakeProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider=self.name,
            model="fake-model",
            content=request.messages[-1].content,
            tool_calls=[],
        )


def _install_fake_provider(app: Any) -> None:
    router = ModelRouter()
    provider = FakeProvider()
    router.register(provider)
    router.set_active(provider.name)
    gateway = AiGateway(router)
    app.state.model_router = router
    app.state.ai_gateway = gateway
    app.state.chat_service = ChatService(
        gateway=gateway,
        tool_registry=app.state.tool_registry,
        settings=get_settings(),
        tool_executor=app.state.tool_executor,
    )


def test_normalize_access_claims() -> None:
    claims = normalize_access_claims(
        {"sub": 99, "agencyId": 12, "tenant": " Demo "}
    )
    assert claims["sub"] == "99"
    assert claims["agencyId"] == "12"
    assert claims["tenant"] == "demo"


def test_chat_requires_bearer_token(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    with TestClient(create_app()) as client:
        _install_fake_provider(client.app)
        response = client.post(
            "/api/v1/chat",
            json={
                "text": "hello",
                "sessionId": "s1",
                "storeId": "507f1f77bcf86cd799439011",
                "language": "hi-IN",
            },
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING"


def test_chat_rejects_expired_token(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    token = make_access_token(rsa_keypair["private_pem"], expired=True)
    with TestClient(create_app()) as client:
        _install_fake_provider(client.app)
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "hello",
                "sessionId": "s1",
                "storeId": "507f1f77bcf86cd799439011",
            },
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_EXPIRED"


def test_chat_rejects_invalid_signature(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = make_access_token(other_pem)
    with TestClient(create_app()) as client:
        _install_fake_provider(client.app)
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "hello",
                "sessionId": "s1",
                "storeId": "507f1f77bcf86cd799439011",
            },
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID"


def test_chat_rejects_invalid_store_id(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    token = make_access_token(rsa_keypair["private_pem"])
    with TestClient(create_app()) as client:
        _install_fake_provider(client.app)
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "hello",
                "sessionId": "s1",
                "storeId": "not-an-object-id",
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STORE_ID_INVALID"


def test_chat_rejects_missing_store_id(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    token = make_access_token(rsa_keypair["private_pem"])
    with TestClient(create_app()) as client:
        _install_fake_provider(client.app)
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "hello", "sessionId": "s1"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_chat_happy_path(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    token = make_access_token(rsa_keypair["private_pem"], sub="owner-1")
    with TestClient(create_app()) as client:
        _install_fake_provider(client.app)
        response = client.post(
            "/api/v1/chat",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": "req-test-1",
            },
            json={
                "text": "Create customer name Ramesh",
                "sessionId": "session-abc",
                "storeId": "507f1f77bcf86cd799439011",
                "language": "hi-IN",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sessionId"] == "session-abc"
    assert payload["userId"] == "owner-1"
    assert payload["requestId"] == "req-test-1"
    assert payload["message"] == "Create customer name Ramesh"
    assert payload["provider"] == "fake"
    assert payload["model"] == "fake-model"
    assert payload["toolCalls"] == []
    assert payload["toolResults"] == []
    assert response.headers["X-Request-ID"] == "req-test-1"
