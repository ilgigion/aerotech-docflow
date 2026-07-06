"""Точка входа FastAPI-приложения Aerotech Docflow."""

import logging
from uuid import UUID

from fastapi import FastAPI, HTTPException, status

from app.repository import job_repository
from app.schemas import (
    JobResponse,
    ScanAcceptedResponse,
    ScanRequest,
)
from app.service import start_scan_job


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


app = FastAPI(
    title="Aerotech Docflow",
    description="Backend-сервис обработки документов",
    version="0.3.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    """Вернуть информацию о сервисе."""

    return {
        "service": "aerotech-docflow",
        "status": "ok",
        "health": "/health",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Проверить доступность сервиса."""

    return {
        "status": "ok",
    }


@app.post(
    "/scan",
    response_model=ScanAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_scan(
    payload: ScanRequest,
) -> ScanAcceptedResponse:
    """Создать задание и начать ожидание PDF."""

    job = job_repository.create(payload)

    start_scan_job(
        request_id=job.request_id,
        payload=payload,
    )

    logging.info(
        "Создано задание: request_id=%s task_id=%s",
        job.request_id,
        job.task_id,
    )

    return ScanAcceptedResponse(
        status="accepted",
        request_id=job.request_id,
        status_url=f"/jobs/{job.request_id}",
    )


@app.get(
    "/jobs/{request_id}",
    response_model=JobResponse,
)
async def get_job(request_id: UUID) -> JobResponse:
    """Получить текущее состояние задания."""

    job = job_repository.get(request_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задание не найдено",
        )

    return job