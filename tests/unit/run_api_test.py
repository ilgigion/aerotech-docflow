from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import api as api_module
from app.document_flow import DocumentProcessResult, ProcessedDocument


client = TestClient(api_module.app)


health_response = client.get("/health")
assert health_response.status_code == 200, health_response.text
assert health_response.json() == {
    "status": "ok",
    "service": "aerotech-docflow",
    "scanner_api": "local",
    "version": "dev",
}


captured_arguments: dict = {}


def successful_flow(**kwargs) -> DocumentProcessResult:
    captured_arguments.update(kwargs)
    processed = ProcessedDocument(
        task_id=kwargs["task_id"],
        operation_id="SCAN_TEST_SUCCESS",
        temp_scan_path=Path("test-incoming.pdf"),
        file_name="НКЛ_260624_135000_001.pdf",
        file_path=Path("D:/archive/НКЛ_260624_135000_001.pdf"),
        idempotency_key=kwargs["idempotency_key"],
        idempotent_replay=False,
    )
    return DocumentProcessResult(
        success=True,
        operation_id=processed.operation_id,
        stage="finished",
        result=processed,
    )


original_flow = api_module.document_flow.process_document_scan_safe
try:
    api_module.document_flow.process_document_scan_safe = successful_flow
    success_response = client.post(
        "/scan",
        json={
            "task_id": "53243",
            "doc_type": "НКЛ",
            "document_number": "001",
            "scanner_profile": "EPSON DS-790WN",
        },
    )
finally:
    api_module.document_flow.process_document_scan_safe = original_flow

assert success_response.status_code == 200, success_response.text
assert success_response.json() == {
    "status": "succeeded",
    "file_name": "НКЛ_260624_135000_001.pdf",
    "operation_id": "SCAN_TEST_SUCCESS",
    "task_id": "53243",
    "idempotency_key": "planfix_53243_НКЛ_001",
    "scan_executed": True,
}
assert captured_arguments["idempotency_key"] == (
    "planfix_53243_НКЛ_001"
)
assert "document_datetime" not in captured_arguments
assert captured_arguments["scanner_profile"] == "EPSON DS-790WN"
assert "file_path" not in success_response.json()


def failed_flow(**kwargs) -> DocumentProcessResult:
    del kwargs
    return DocumentProcessResult(
        success=False,
        operation_id="SCAN_TEST_TIMEOUT",
        stage="scanner",
        error_code="scanner_timeout",
        operator_message="Сканер не завершил работу вовремя.",
    )


try:
    api_module.document_flow.process_document_scan_safe = failed_flow
    failure_response = client.post(
        "/scan",
        json={
            "task_id": "53243",
            "doc_type": "НКЛ",
            "document_number": "001",
            "scanner_profile": "EPSON DS-790WN",
            "idempotency_key": "request-53243",
        },
    )
finally:
    api_module.document_flow.process_document_scan_safe = original_flow

assert failure_response.status_code == 503, failure_response.text
assert failure_response.json()["status"] == "failed"
assert failure_response.json()["error_code"] == "scanner_timeout"
assert failure_response.json()["operation_id"] == "SCAN_TEST_TIMEOUT"
assert api_module._error_status("scanner_connection_error") == 503
assert api_module._error_status("scanner_not_found") == 503


invalid_response = client.post(
    "/scan",
    json={
        "task_id": "53243",
        "doc_type": "НКЛ",
    },
)
assert invalid_response.status_code == 422, invalid_response.text
assert invalid_response.json()["error_code"] == "validation_error"

invalid_identity_response = client.post(
    "/scan",
    json={
        "task_id": "53243",
        "doc_type": "<>",
        "document_number": "001",
        "scanner_profile": "EPSON DS-790WN",
        "idempotency_key": "explicit-key",
    },
)
assert invalid_identity_response.status_code == 422, invalid_identity_response.text
assert invalid_identity_response.json()["error_code"] == "validation_error"

legacy_datetime_response = client.post(
    "/scan",
    json={
        "task_id": "53243",
        "doc_type": "НКЛ",
        "document_datetime": "2026-06-24T13:50:00",
        "document_number": "001",
        "scanner_profile": "EPSON DS-790WN",
    },
)
assert legacy_datetime_response.status_code == 422, legacy_datetime_response.text
assert legacy_datetime_response.json()["error_code"] == "validation_error"

invalid_profile_response = client.post(
    "/scan",
    json={
        "task_id": "53243",
        "doc_type": "НКЛ",
        "document_number": "001",
        "scanner_profile": "EPSON\nINJECTED",
    },
)
assert invalid_profile_response.status_code == 422, invalid_profile_response.text
assert invalid_profile_response.json()["error_code"] == "validation_error"

print("API UNIT TEST OK")
