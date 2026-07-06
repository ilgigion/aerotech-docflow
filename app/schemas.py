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
    DONE = "done"
    FAILED = "failed"


class ScanRequest(BaseModel):
    """JSON, который приходит в POST /scan."""

    task_id: int = Field(
        gt=0,
        description="Идентификатор задачи во внешней системе",
        examples=[52418],
    )

    document_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description="Код типа документа",
        examples=["UPD"],
    )

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Дополнительные данные запроса",
    )


class ScanAcceptedResponse(BaseModel):
    """Ответ после принятия POST /scan."""

    status: Literal["accepted"]
    request_id: UUID
    status_url: str


class JobResponse(BaseModel):
    """Текущее состояние задания."""

    request_id: UUID
    task_id: int
    document_type: str | None
    context: dict[str, Any]

    status: JobStatus

    created_at: datetime
    updated_at: datetime

    result_file: str | None = None
    error: str | None = None