from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import secrets

from app.locks import ScannerLockError, ScannerLockSettings, scanner_lock
from app.naming import NamingError, build_document_filename
from app.scanner import ScannerError, ScannerSettings, load_settings_from_env, scan_document
from app.storage import (
    StorageError,
    StorageSettings,
    StoredDocument,
    load_storage_settings_from_env,
    store_document,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessedDocument:
    """
    Итог полного процесса сканирования и сохранения.
    """

    task_id: str
    operation_id: str
    temp_scan_path: Path
    file_name: str
    file_path: Path


@dataclass(frozen=True)
class DocumentProcessResult:
    """
    Безопасный результат для будущего FastAPI/Planfix.
    """

    success: bool
    operation_id: str
    stage: str
    result: ProcessedDocument | None = None
    error_code: str | None = None
    operator_message: str | None = None
    technical_message: str | None = None
    temp_scan_path: Path | None = None
    details: dict | None = None


def build_operation_id() -> str:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)
    return f"SCAN_{now}_{suffix}"


def get_effective_scanner_settings(
    scanner_settings: ScannerSettings | None,
) -> ScannerSettings:
    if scanner_settings is not None:
        return scanner_settings

    return load_settings_from_env()


def get_effective_storage_settings(
    storage_settings: StorageSettings | None,
) -> StorageSettings:
    if storage_settings is not None:
        return storage_settings

    return load_storage_settings_from_env()


def get_lock_path(
    scanner_settings: ScannerSettings,
    lock_settings: ScannerLockSettings | None,
) -> Path:
    if lock_settings and lock_settings.lock_file:
        return Path(lock_settings.lock_file)

    return Path(scanner_settings.incoming_dir) / ".scanner.lock"


def prevalidate_before_lock(
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
) -> str:
    """
    Проверяем входные данные до захвата lock.
    """

    return build_document_filename(
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
    )


def process_document_scan(
    task_id: int | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    *,
    scanner_settings: ScannerSettings | None = None,
    storage_settings: StorageSettings | None = None,
    lock_settings: ScannerLockSettings | None = None,
    use_lock: bool = True,
) -> ProcessedDocument:
    """
    Полный процесс:

    1. Проверяем входные данные для имени.
    2. Захватываем file lock сканера.
    3. Сканируем документ во временный PDF.
    4. Атомарно переносим PDF в архив.
    5. Освобождаем lock.
    6. Возвращаем финальное имя и путь.
    """

    task_id_str = str(task_id).strip()
    operation_id = build_operation_id()

    effective_scanner_settings = get_effective_scanner_settings(scanner_settings)
    effective_storage_settings = get_effective_storage_settings(storage_settings)

    expected_file_name = prevalidate_before_lock(
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
    )

    lock_path = get_lock_path(
        scanner_settings=effective_scanner_settings,
        lock_settings=lock_settings,
    )

    logger.info(
        "Document scan process started: operation_id=%s task_id=%s expected_file_name=%s lock_path=%s",
        operation_id,
        task_id_str,
        expected_file_name,
        lock_path,
    )

    if lock_settings is None:
        lock_settings = ScannerLockSettings()

    if use_lock:
        lock_context = scanner_lock(
            lock_path=lock_path,
            operation_id=operation_id,
            task_id=task_id_str,
            settings=lock_settings,
        )
    else:
        lock_context = _NullLockContext()

    with lock_context:
        temp_scan_path = scan_document(
            task_id=task_id_str,
            settings=effective_scanner_settings,
            operation_id=operation_id,
        )

        stored_document: StoredDocument = store_document(
            source_path=temp_scan_path,
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
            settings=effective_storage_settings,
            operation_id=operation_id,
        )

    processed_document = ProcessedDocument(
        task_id=task_id_str,
        operation_id=operation_id,
        temp_scan_path=temp_scan_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
    )

    logger.info(
        "Document scan process finished: operation_id=%s task_id=%s file_name=%s file_path=%s",
        operation_id,
        task_id_str,
        processed_document.file_name,
        processed_document.file_path,
    )

    return processed_document


def retry_store_existing_scan(
    task_id: int | str,
    source_path: Path | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    *,
    storage_settings: StorageSettings | None = None,
) -> ProcessedDocument:
    """
    Повторяет только сохранение уже существующего временного PDF.

    Используется, если:
        сканирование прошло успешно,
        но перенос в архив упал из-за прав/сети/архивной папки.

    Сканер повторно не запускается.
    """

    task_id_str = str(task_id).strip()
    operation_id = build_operation_id()
    source_path = Path(source_path)

    effective_storage_settings = get_effective_storage_settings(storage_settings)

    logger.info(
        "Retry store existing scan started: operation_id=%s task_id=%s source_path=%s",
        operation_id,
        task_id_str,
        source_path,
    )

    stored_document = store_document(
        source_path=source_path,
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
        settings=effective_storage_settings,
        operation_id=operation_id,
    )

    result = ProcessedDocument(
        task_id=task_id_str,
        operation_id=operation_id,
        temp_scan_path=source_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
    )

    logger.info(
        "Retry store existing scan finished: operation_id=%s task_id=%s file_name=%s file_path=%s",
        operation_id,
        task_id_str,
        result.file_name,
        result.file_path,
    )

    return result


def process_document_scan_safe(
    task_id: int | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    *,
    scanner_settings: ScannerSettings | None = None,
    storage_settings: StorageSettings | None = None,
    lock_settings: ScannerLockSettings | None = None,
    use_lock: bool = True,
) -> DocumentProcessResult:
    """
    Безопасная обёртка.

    Не выбрасывает ожидаемые ошибки наружу,
    а возвращает DocumentProcessResult.
    """

    fallback_operation_id = build_operation_id()

    try:
        result = process_document_scan(
            task_id=task_id,
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
            scanner_settings=scanner_settings,
            storage_settings=storage_settings,
            lock_settings=lock_settings,
            use_lock=use_lock,
        )

        return DocumentProcessResult(
            success=True,
            operation_id=result.operation_id,
            stage="finished",
            result=result,
        )

    except ScannerLockError as exc:
        return DocumentProcessResult(
            success=False,
            operation_id=fallback_operation_id,
            stage="lock",
            error_code=exc.code,
            operator_message=exc.operator_message,
            technical_message=exc.technical_message,
            details=exc.to_log_dict(),
        )

    except NamingError as exc:
        return DocumentProcessResult(
            success=False,
            operation_id=fallback_operation_id,
            stage="naming",
            error_code=exc.code,
            operator_message=exc.operator_message,
            technical_message=exc.technical_message,
            details=exc.to_log_dict(),
        )

    except ScannerError as exc:
        return DocumentProcessResult(
            success=False,
            operation_id=fallback_operation_id,
            stage="scanner",
            error_code=exc.code,
            operator_message=exc.operator_message,
            technical_message=exc.technical_message,
            temp_scan_path=exc.output_path,
            details=exc.to_log_dict(),
        )

    except StorageError as exc:
        return DocumentProcessResult(
            success=False,
            operation_id=fallback_operation_id,
            stage="storage",
            error_code=exc.code,
            operator_message=exc.operator_message,
            technical_message=exc.technical_message,
            temp_scan_path=exc.source_path,
            details=exc.to_log_dict(),
        )


class _NullLockContext:
    """
    Используется только для тестов, если use_lock=False.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None
