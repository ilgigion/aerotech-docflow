from __future__ import annotations

from datetime import datetime
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import document_flow
from app.naming import normalize_doc_type, normalize_document_number, normalize_filename_part


logger = logging.getLogger(__name__)

app = FastAPI(title="Aerotech Docflow Local API", version="dev")


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: str = Field(min_length=1, max_length=120)
    doc_type: str = Field(min_length=1, max_length=30)
    document_datetime: datetime
    document_number: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("task_id", "doc_type", "document_number")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value:
            raise ValueError("field must not be blank")
        return value


class ScanSucceededResponse(BaseModel):
    status: str = "succeeded"
    file_name: str
    operation_id: str
    task_id: str
    idempotency_key: str
    scan_executed: bool


def build_default_idempotency_key(payload: ScanRequest) -> str:
    """Build a stable compatibility key without calling any external system."""

    task_part = normalize_filename_part(payload.task_id, "task_id")
    if not task_part:
        raise ValueError("task_id has no usable characters")

    return "_".join(
        (
            "planfix",
            task_part,
            normalize_doc_type(payload.doc_type),
            payload.document_datetime.strftime("%Y%m%dT%H%M%S"),
            normalize_document_number(payload.document_number),
        )
    )


def validate_document_identity(payload: ScanRequest) -> None:
    task_part = normalize_filename_part(payload.task_id, "task_id")
    if not task_part:
        raise ValueError("task_id has no usable characters")
    normalize_doc_type(payload.doc_type)
    normalize_document_number(payload.document_number)


def _error_status(error_code: str | None) -> int:
    if error_code in {
        "scanner_busy",
        "scanner_locked",
        "idempotency_conflict",
        "idempotency_key_request_conflict",
        "already_processing",
        "idempotency_in_progress",
    }:
        return 409

    if error_code in {
        "scanner_timeout",
        "manual_recovery_required",
        "scanner_process_still_running",
    }:
        return 503

    return 500


def _failed_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    operation_id: str,
    task_id: str,
    idempotency_key: str | None = None,
) -> JSONResponse:
    content = {
        "status": "failed",
        "error_code": error_code,
        "message": message,
        "operation_id": operation_id,
        "task_id": task_id,
    }
    if idempotency_key is not None:
        content["idempotency_key"] = idempotency_key
    return JSONResponse(status_code=status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=422,
        content={
            "status": "failed",
            "error_code": "validation_error",
            "message": "Некорректные входные данные",
            "details": jsonable_encoder(exc.errors()),
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "aerotech-docflow",
        "scanner_api": "local",
        "version": "dev",
    }


@app.post("/scan", response_model=ScanSucceededResponse)
def scan(payload: ScanRequest) -> ScanSucceededResponse | JSONResponse:
    request_operation_id = document_flow.build_operation_id()

    try:
        validate_document_identity(payload)
        effective_idempotency_key = (
            payload.idempotency_key or build_default_idempotency_key(payload)
        )
    except (TypeError, ValueError) as exc:
        return _failed_response(
            status_code=422,
            error_code="validation_error",
            message=str(exc),
            operation_id=request_operation_id,
            task_id=payload.task_id,
        )

    try:
        flow_result = document_flow.process_document_scan_safe(
            task_id=payload.task_id,
            doc_type=payload.doc_type,
            document_datetime=payload.document_datetime,
            document_number=payload.document_number,
            idempotency_key=effective_idempotency_key,
        )
    except Exception:
        logger.exception(
            "Unexpected local scan API failure: operation_id=%s task_id=%s",
            request_operation_id,
            payload.task_id,
        )
        return _failed_response(
            status_code=500,
            error_code="internal_error",
            message="Внутренняя ошибка локального сервера сканирования",
            operation_id=request_operation_id,
            task_id=payload.task_id,
            idempotency_key=effective_idempotency_key,
        )

    if not flow_result.success or flow_result.result is None:
        status_code = (
            422
            if flow_result.stage == "naming"
            else _error_status(flow_result.error_code)
        )
        return _failed_response(
            status_code=status_code,
            error_code=flow_result.error_code or "document_flow_failed",
            message=flow_result.operator_message or "Не удалось обработать документ",
            operation_id=flow_result.operation_id,
            task_id=payload.task_id,
            idempotency_key=effective_idempotency_key,
        )

    processed = flow_result.result
    return ScanSucceededResponse(
        file_name=processed.file_name,
        operation_id=processed.operation_id,
        task_id=payload.task_id,
        idempotency_key=processed.idempotency_key or effective_idempotency_key,
        scan_executed=not processed.idempotent_replay,
    )
