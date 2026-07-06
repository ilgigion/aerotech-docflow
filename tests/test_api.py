"""Тесты HTTP API."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.schemas import ScanRequest


VALID_SCAN_REQUEST = {
    "external_request_id": "planfix-scan-52418-001",
    "task_id": 52418,
    "document_type": "UPD",
    "document_number": "2455/1",
    "user_code": "IV",
    "context": {
        "source": "planfix",
    },
}


def test_root(
    client: TestClient,
) -> None:
    """Корневой endpoint возвращает информацию о сервисе."""

    response = client.get("/")

    assert response.status_code == 200

    body = response.json()

    assert body["service"] == "aerotech-docflow"
    assert body["status"] == "ok"
    assert body["health"] == "/health"
    assert body["docs"] == "/docs"
    assert body["jobs"] == "/jobs"


def test_health(
    client: TestClient,
) -> None:
    """Health-check возвращает успешный статус."""

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


def test_create_scan_job(
    client: TestClient,
    started_jobs: list[tuple[UUID, ScanRequest]],
) -> None:
    """POST /scan создаёт новое задание."""

    response = client.post(
        "/scan",
        json=VALID_SCAN_REQUEST,
    )

    assert response.status_code == 202

    body = response.json()

    assert body["status"] == "accepted"
    assert body["created"] is True
    assert body["request_id"]
    assert body["job_status"] == "accepted"
    assert body["status_url"] == (
        f"/jobs/{body['request_id']}"
    )

    assert len(started_jobs) == 1


def test_get_created_job(
    client: TestClient,
) -> None:
    """Созданное задание можно получить по request_id."""

    create_response = client.post(
        "/scan",
        json=VALID_SCAN_REQUEST,
    )

    assert create_response.status_code == 202

    request_id = (
        create_response.json()["request_id"]
    )

    response = client.get(
        f"/jobs/{request_id}"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["request_id"] == request_id
    assert (
        body["external_request_id"]
        == "planfix-scan-52418-001"
    )
    assert body["task_id"] == 52418
    assert body["document_type"] == "UPD"
    assert body["document_number"] == "2455/1"
    assert body["user_code"] == "IV"
    assert body["status"] == "accepted"
    assert body["result_file"] is None
    assert body["sha256"] is None
    assert body["error"] is None


def test_list_jobs(
    client: TestClient,
) -> None:
    """GET /jobs возвращает историю заданий."""

    first_request = {
        **VALID_SCAN_REQUEST,
        "external_request_id": "request-100",
        "task_id": 100,
    }

    second_request = {
        **VALID_SCAN_REQUEST,
        "external_request_id": "request-200",
        "task_id": 200,
    }

    first_response = client.post(
        "/scan",
        json=first_request,
    )

    second_response = client.post(
        "/scan",
        json=second_request,
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202

    response = client.get("/jobs")

    assert response.status_code == 200

    jobs = response.json()

    assert len(jobs) == 2
    assert jobs[0]["task_id"] == 200
    assert jobs[1]["task_id"] == 100


def test_unknown_job_returns_404(
    client: TestClient,
) -> None:
    """Неизвестный request_id возвращает 404."""

    response = client.get(
        f"/jobs/{uuid4()}"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Задание не найдено",
    }


def test_invalid_task_id_returns_422(
    client: TestClient,
) -> None:
    """task_id должен быть больше нуля."""

    request_body = {
        **VALID_SCAN_REQUEST,
        "task_id": 0,
    }

    response = client.post(
        "/scan",
        json=request_body,
    )

    assert response.status_code == 422


def test_missing_document_number_returns_422(
    client: TestClient,
) -> None:
    """Номер документа является обязательным."""

    request_body = VALID_SCAN_REQUEST.copy()
    request_body.pop("document_number")

    response = client.post(
        "/scan",
        json=request_body,
    )

    assert response.status_code == 422


def test_empty_user_code_returns_422(
    client: TestClient,
) -> None:
    """Код пользователя не может быть пустым."""

    request_body = {
        **VALID_SCAN_REQUEST,
        "user_code": "",
    }

    response = client.post(
        "/scan",
        json=request_body,
    )

    assert response.status_code == 422


def test_duplicate_scan_request_returns_existing_job(
    client: TestClient,
    started_jobs: list[tuple[UUID, ScanRequest]],
) -> None:
    """Повторный запрос не запускает второй процесс."""

    first_response = client.post(
        "/scan",
        json=VALID_SCAN_REQUEST,
    )

    second_response = client.post(
        "/scan",
        json=VALID_SCAN_REQUEST,
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 200

    first_body = first_response.json()
    second_body = second_response.json()

    assert first_body["created"] is True
    assert first_body["status"] == "accepted"

    assert second_body["created"] is False
    assert second_body["status"] == "existing"

    assert (
        second_body["request_id"]
        == first_body["request_id"]
    )

    assert (
        second_body["job_status"]
        == "accepted"
    )

    assert len(started_jobs) == 1


def test_same_external_id_with_other_data_returns_409(
    client: TestClient,
) -> None:
    """Один внешний ID нельзя использовать с другими данными."""

    first_response = client.post(
        "/scan",
        json=VALID_SCAN_REQUEST,
    )

    assert first_response.status_code == 202

    conflicting_request = {
        **VALID_SCAN_REQUEST,
        "document_number": "9999",
    }

    second_response = client.post(
        "/scan",
        json=conflicting_request,
    )

    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": (
            "external_request_id уже используется "
            "для другого набора данных"
        )
    }


def test_external_request_id_is_required(
    client: TestClient,
) -> None:
    """Внешний идентификатор запроса обязателен."""

    request_body = VALID_SCAN_REQUEST.copy()
    request_body.pop("external_request_id")

    response = client.post(
        "/scan",
        json=request_body,
    )

    assert response.status_code == 422