"""API-level tests for /api/v1/admin/* (Phase 7)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import GenerationRequest, GenerationResponse
from tests.conftest import StaticPemVerifier, make_access_token

STORE_ID = "507f1f77bcf86cd799439011"


class FakeProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider=self.name, model="fake-model", content="ok", tool_calls=[]
        )


def _install_provider(app: Any) -> None:
    router = ModelRouter()
    provider = FakeProvider()
    router.register(provider)
    router.set_active(provider.name)
    app.state.model_router = router


def _client_with_verifier(monkeypatch: Any, rsa_keypair: dict[str, Any]):
    monkeypatch.setattr(
        "app.core.security.get_token_verifier",
        lambda: StaticPemVerifier(rsa_keypair["public_pem"]),
    )
    return TestClient(create_app())


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_model_requires_auth(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        response = client.get("/api/v1/admin/model")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING"


def test_admin_model_rejects_store_roles(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        for role in ("store_owner", "store_staff", "manager"):
            token = make_access_token(rsa_keypair["private_pem"], role=role)
            response = client.get("/api/v1/admin/model", headers=_auth(token))
            assert response.status_code == 403, role
            assert response.json()["error"]["code"] == "ADMIN_FORBIDDEN"


def test_admin_model_get_returns_env_defaults(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(rsa_keypair["private_pem"], role="admin")
        response = client.get("/api/v1/admin/model", headers=_auth(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "fake"
    assert payload["model"] == "gpt-4o-mini"
    assert payload["availableProviders"] == ["fake"]
    assert "gpt-4o-mini" in payload["allowedModels"]
    assert payload["updatedBy"] is None


def test_admin_model_put_rejects_unknown_provider(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(rsa_keypair["private_pem"], role="super_admin")
        response = client.put(
            "/api/v1/admin/model",
            headers=_auth(token),
            json={"provider": "nope", "model": "gpt-4o-mini"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ADMIN_PROVIDER_UNKNOWN"


def test_admin_model_put_rejects_disallowed_model(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(rsa_keypair["private_pem"], role="super_admin")
        response = client.put(
            "/api/v1/admin/model",
            headers=_auth(token),
            json={"provider": "fake", "model": "gpt-superexpensive"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ADMIN_MODEL_NOT_ALLOWED"


def test_admin_model_put_persists_selection(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    monkeypatch.setenv("AI_OPENAI_ALLOWED_MODELS", '["gpt-4o"]')
    from app.config import get_settings

    get_settings.cache_clear()
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(
            rsa_keypair["private_pem"], sub="admin-1", role="super_admin"
        )
        put_response = client.put(
            "/api/v1/admin/model",
            headers=_auth(token),
            json={"provider": "fake", "model": "gpt-4o"},
        )
        get_response = client.get("/api/v1/admin/model", headers=_auth(token))
    assert put_response.status_code == 200
    payload = get_response.json()
    assert payload["provider"] == "fake"
    assert payload["model"] == "gpt-4o"
    assert payload["updatedBy"] == "admin-1"
    assert payload["updatedAt"]


def test_admin_usage_validates_store_id(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(rsa_keypair["private_pem"], role="admin")
        response = client.get(
            "/api/v1/admin/usage/not-an-id", headers=_auth(token)
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STORE_ID_INVALID"


def test_admin_usage_returns_counters_and_caps(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(rsa_keypair["private_pem"], role="admin")
        response = client.get(
            f"/api/v1/admin/usage/{STORE_ID}", headers=_auth(token)
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["storeId"] == STORE_ID
    assert payload["requests"] == 0
    assert payload["totalTokens"] == 0
    assert payload["dailyTokenCap"] == 0
    assert payload["dailyCostCapUsd"] == 0


def test_admin_metrics_snapshot_shape(
    monkeypatch: Any, rsa_keypair: dict[str, Any]
) -> None:
    with _client_with_verifier(monkeypatch, rsa_keypair) as client:
        _install_provider(client.app)
        token = make_access_token(rsa_keypair["private_pem"], role="admin")
        response = client.get("/api/v1/admin/metrics", headers=_auth(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["chat"]["requests"] == 0
    assert payload["provider"]["errors"] == 0
    assert payload["tools"]["successRate"] is None
