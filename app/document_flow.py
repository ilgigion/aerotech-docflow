from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.scanner import ScannerSettings, scan_document
from app.storage import StorageSettings, StoredDocument, store_document


@dataclass(frozen=True)
class ProcessedDocument:
    """
    Итог полного процесса сканирования и сохранения.

    task_id:
        номер задачи/операции

    temp_scan_path:
        путь, куда scanner.py сначала создал временный PDF.
        После переноса этот файл уже может не существовать,
        потому что storage.py переносит его в архив.

    file_name:
        финальное имя файла

    file_path:
        финальный путь в архиве
    """

    task_id: str
    temp_scan_path: Path
    file_name: str
    file_path: Path


def process_document_scan(
    task_id: int | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    *,
    scanner_settings: ScannerSettings | None = None,
    storage_settings: StorageSettings | None = None,
) -> ProcessedDocument:
    """
    Полный процесс:

    1. Сканируем документ.
    2. Получаем временный PDF.
    3. Формируем финальное имя.
    4. Создаём папку архива, если её нет.
    5. Переносим PDF в архив.
    6. Возвращаем финальное имя и путь.

    Важно:
        Ошибки здесь специально не перехватываем.
        Их уже умеют отдавать конкретные модули:

        ScannerError — проблема сканирования
        NamingError  — проблема имени
        StorageError — проблема переноса в архив
    """

    task_id_str = str(task_id).strip()

    temp_scan_path = scan_document(
        task_id=task_id_str,
        settings=scanner_settings,
    )

    stored_document: StoredDocument = store_document(
        source_path=temp_scan_path,
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
        settings=storage_settings,
    )

    return ProcessedDocument(
        task_id=task_id_str,
        temp_scan_path=temp_scan_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
    )