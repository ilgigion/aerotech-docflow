"""Бизнес-логика обработки заданий на сканирование."""

import asyncio
import logging
from uuid import UUID

from app.config import settings
from app.repository import job_repository
from app.scanner import ScannerTimeoutError, wait_for_new_pdf
from app.schemas import JobStatus, ScanRequest


logger = logging.getLogger(__name__)


# Один физический сканер может обслуживать только одно задание одновременно.
_scanner_lock = asyncio.Lock()

# Храним ссылки на фоновые задачи, пока они не завершились.
_running_tasks: set[asyncio.Task[None]] = set()


async def process_scan_job(
    request_id: UUID,
    payload: ScanRequest,
) -> None:
    """Дождаться PDF, созданного сканером."""

    try:
        logger.info(
            "Задание ожидает освобождения сканера: "
            "request_id=%s task_id=%s",
            request_id,
            payload.task_id,
        )

        # Пока другое задание работает со сканером,
        # текущее остаётся в статусе accepted.
        async with _scanner_lock:
            job_repository.update_status(
                request_id=request_id,
                status=JobStatus.WAITING_FOR_FILE,
            )

            logger.info(
                "Ожидание PDF: request_id=%s task_id=%s folder=%s",
                request_id,
                payload.task_id,
                settings.scan_inbox,
            )

            pdf_path = await wait_for_new_pdf(
                folder=settings.scan_inbox,
                timeout_seconds=settings.scan_timeout_seconds,
                poll_interval_seconds=(
                    settings.scan_poll_interval_seconds
                ),
                stable_checks=settings.scan_stable_checks,
            )

            job_repository.update_status(
                request_id=request_id,
                status=JobStatus.FILE_RECEIVED,
            )

            job_repository.set_result_file(
                request_id=request_id,
                result_file=str(pdf_path),
            )

            logger.info(
                "PDF получен: request_id=%s file=%s",
                request_id,
                pdf_path,
            )

            # Позже здесь появятся:
            # 1. переименование;
            # 2. перемещение в архив;
            # 3. вычисление SHA-256;
            # 4. обновление Planfix.

            job_repository.update_status(
                request_id=request_id,
                status=JobStatus.DONE,
            )

            logger.info(
                "Обработка завершена: request_id=%s",
                request_id,
            )

    except ScannerTimeoutError as error:
        logger.warning(
            "Истёк таймаут ожидания PDF: request_id=%s",
            request_id,
        )

        job_repository.update_status(
            request_id=request_id,
            status=JobStatus.FAILED,
            error=str(error),
        )

    except Exception as error:
        logger.exception(
            "Ошибка обработки задания: request_id=%s",
            request_id,
        )

        job_repository.update_status(
            request_id=request_id,
            status=JobStatus.FAILED,
            error=str(error),
        )


def start_scan_job(
    request_id: UUID,
    payload: ScanRequest,
) -> None:
    """Запустить обработку в отдельной asyncio-задаче."""

    task = asyncio.create_task(
        process_scan_job(
            request_id=request_id,
            payload=payload,
        )
    )

    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)