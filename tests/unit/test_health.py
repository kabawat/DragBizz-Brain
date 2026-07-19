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
    assert response.json() == {
        "status": "ready",
        "service": "DragBizz AI",
        "dependencies": [{"name": "http_client", "status": "ok"}],
    }


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "invalid request id"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"
