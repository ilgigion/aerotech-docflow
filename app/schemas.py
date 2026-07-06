"""Модели входящих запросов и ответов API."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Возможные состояния задания."""

    ACCEPTED = "accepted"
    WAITING_FOR_FILE = "waiting_for_file"
    FILE_RECEIVED = "file_received"
    ARCHIVING = "archiving"
    DONE = "done"
    FAILED = "failed"


class ScanRequest(BaseModel):
    """JSON, который приходит в POST /scan."""

    external_request_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Уникальный идентификатор запроса внешней системы. "
            "Повторный запрос с тем же значением не создаёт новое задание."
        ),
        examples=["planfix-scan-52418-001"],
    )

    task_id: int = Field(
        gt=0,
        description="Идентификатор задачи во внешней системе",
        examples=[52418],
    )

    document_type: str = Field(
        min_length=1,
        max_length=32,
        description="Код типа документа",
        examples=["UPD"],
    )

    document_number: str = Field(
        min_length=1,
        max_length=100,
        description="Номер документа",
        examples=["2455/1"],
    )

    user_code: str = Field(
        min_length=1,
        max_length=20,
        description="Код пользователя",
        examples=["IV"],
    )

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Дополнительные данные запроса",
    )


class ScanAcceptedResponse(BaseModel):
    """Ответ на POST /scan."""

    status: Literal["accepted", "existing"]
    created: bool

    request_id: UUID
    job_status: JobStatus
    status_url: str


class JobResponse(BaseModel):
    """Текущее состояние задания."""

    request_id: UUID

    # У старых записей, созданных до миграции, значение будет None.
    external_request_id: str | None

    task_id: int
    document_type: str
    document_number: str
    user_code: str

    context: dict[str, Any]
    status: JobStatus

    created_at: datetime
    updated_at: datetime

    source_file: str | None = None
    result_file: str | None = None
    result_filename: str | None = None
    sha256: str | None = None

    error: str | None = None