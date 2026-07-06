"""Тесты HTTP API."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root() -> None:
    response = client.get("/")

    assert response.status_code == 200

    body = response.json()

    assert body["service"] == "aerotech-docflow"
    assert body["status"] == "ok"


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


def test_create_scan_job() -> None:
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

    assert response.status_code == 202

    body = response.json()

    assert body["status"] == "accepted"
    assert body["request_id"]
    assert body["status_url"] == (
        f"/jobs/{body['request_id']}"
    )


def test_get_created_job() -> None:
    create_response = client.post(
        "/scan",
        json={
            "task_id": 100,
            "document_type": "NKL",
        },
    )

    assert create_response.status_code == 202

    request_id = create_response.json()["request_id"]

    response = client.get(
        f"/jobs/{request_id}"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["request_id"] == request_id
    assert body["task_id"] == 100
    assert body["document_type"] == "NKL"
    assert body["status"] in {
        "accepted",
        "processing",
        "done",
    }


def test_unknown_job_returns_404() -> None:
    request_id = uuid4()

    response = client.get(
        f"/jobs/{request_id}"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Задание не найдено",
    }


def test_invalid_task_id_returns_422() -> None:
    response = client.post(
        "/scan",
        json={
            "task_id": 0,
        },
    )

    assert response.status_code == 422


def test_missing_task_id_returns_422() -> None:
    response = client.post(
        "/scan",
        json={
            "document_type": "UPD",
        },
    )

    assert response.status_code == 422