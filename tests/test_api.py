"""Тесты HTTP API."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["service"] == "aerotech-docflow"


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_scan_request() -> None:
    response = client.post(
        "/scan",
        json={
            "task_id": 52418,
            "document_type": "UPD",
            "context": {
                "source": "planfix",
            },
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["request_id"]
    assert body["message"] == "Запрос принят в обработку"


def test_scan_rejects_invalid_task_id() -> None:
    response = client.post(
        "/scan",
        json={
            "task_id": 0,
        },
    )

    assert response.status_code == 422


def test_scan_rejects_missing_task_id() -> None:
    response = client.post(
        "/scan",
        json={
            "document_type": "UPD",
        },
    )

    assert response.status_code == 422