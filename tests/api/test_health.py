"""API-level tests for /api/v1/health and /api/v1/ready."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_health_endpoint_returns_service_status() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "DragBizz AI"
    assert response.headers["X-Request-ID"]


def test_readiness_endpoint_checks_initialized_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hermetic: don't depend on whether a local Qdrant / API key exists.
    # Env vars beat .env in pydantic-settings; port 59999 is a dead port.
    monkeypatch.setenv("AI_QDRANT_URL", "http://127.0.0.1:59999")
    monkeypatch.setenv("AI_OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/ready")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["service"] == "DragBizz AI"
    names = {item["name"]: item["status"] for item in body["dependencies"]}
    assert names["http_client"] == "ok"
    assert names["ai_provider"] == "unavailable"
    assert names["qdrant"] == "unavailable"


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "invalid request id"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"
