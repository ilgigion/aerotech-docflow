"""Схемы входящих запросов и ответов API."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    """Запрос на запуск обработки документа."""

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


class ScanResponse(BaseModel):
    """Ответ после принятия запроса."""

    status: Literal["ok"]
    request_id: UUID
    message: str