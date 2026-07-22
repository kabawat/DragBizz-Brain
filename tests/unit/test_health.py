from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_service_status() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "DragBizz AI"
    assert response.headers["X-Request-ID"]


def test_readiness_endpoint_checks_initialized_dependencies() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/ready")

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
