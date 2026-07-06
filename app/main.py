"""Точка входа FastAPI-приложения Aerotech Docflow."""

import logging
from uuid import uuid4

from fastapi import FastAPI

from app.schemas import ScanRequest, ScanResponse
from app.service import process_scan_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(
    title="Aerotech Docflow",
    description="Backend-сервис обработки и сканирования документов",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    """Информация о сервисе."""

    return {
        "service": "aerotech-docflow",
        "status": "ok",
        "health": "/health",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Проверка доступности приложения."""

    return {"status": "ok"}


@app.post("/scan", response_model=ScanResponse)
async def start_scan(payload: ScanRequest) -> ScanResponse:
    """Принять запрос и запустить обработку документа."""

    request_id = uuid4()

    await process_scan_request(
        request_id=request_id,
        payload=payload,
    )

    return ScanResponse(
        status="ok",
        request_id=request_id,
        message="Запрос принят в обработку",
    )