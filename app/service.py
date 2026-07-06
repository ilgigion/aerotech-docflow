"""Бизнес-логика обработки запроса на сканирование."""

import logging
from uuid import UUID

from app.schemas import ScanRequest

logger = logging.getLogger(__name__)


async def process_scan_request(
    request_id: UUID,
    payload: ScanRequest,
) -> None:
    """Заглушка процесса обработки документа."""

    logger.info(
        "Запущена обработка request_id=%s task_id=%s document_type=%s",
        request_id,
        payload.task_id,
        payload.document_type,
    )

    # Дальше здесь появятся этапы:
    #
    # 1. получение информации из Planfix;
    # 2. запуск сканера;
    # 3. ожидание PDF;
    # 4. формирование имени;
    # 5. сохранение файла;
    # 6. обновление Planfix.