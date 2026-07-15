from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import secrets

from app.idempotency import (
    IdempotencyError,
    IdempotencyInProgressError,
    IdempotencyRecord,
    IdempotencySettings,
    begin_idempotent_operation,
    load_idempotency_settings_from_env,
    mark_failed,
    mark_scanned,
    mark_storing,
    mark_succeeded,
)
from app.locks import ScannerLockError, ScannerLockSettings, scanner_lock
from app.monthly_file_logging import configure_monthly_file_logging_from_env
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
    idempotency_key: str | None = None
    idempotent_replay: bool = False


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


def get_effective_idempotency_settings(
    idempotency_settings: IdempotencySettings | None,
    scanner_settings: ScannerSettings,
) -> IdempotencySettings:
    if idempotency_settings is not None:
        return idempotency_settings

    return load_idempotency_settings_from_env(
        default_incoming_dir=Path(scanner_settings.incoming_dir),
    )


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


def _processed_from_existing_idempotency_record(
    *,
    task_id: str,
    record: IdempotencyRecord,
) -> ProcessedDocument:
    if not record.final_file_path:
        raise IdempotencyError(
            code="idempotency_missing_final_path",
            operator_message="Операция уже отмечена выполненной, но путь к файлу не сохранён.",
            technical_message="Succeeded idempotency record has no final_file_path",
            idempotency_key=record.idempotency_key,
            record=record.to_dict(),
        )

    final_path = Path(record.final_file_path)
    temp_path = Path(record.temp_scan_path) if record.temp_scan_path else final_path

    return ProcessedDocument(
        task_id=task_id,
        operation_id=record.operation_id,
        temp_scan_path=temp_path,
        file_name=record.final_file_name or final_path.name,
        file_path=final_path,
        idempotency_key=record.idempotency_key,
        idempotent_replay=True,
    )


def _storage_retry_from_idempotency_record(
    *,
    task_id: str,
    operation_id: str,
    record: IdempotencyRecord,
    record_path: Path,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    storage_settings: StorageSettings,
) -> ProcessedDocument:
    if not record.temp_scan_path:
        raise IdempotencyError(
            code="idempotency_missing_temp_path",
            operator_message="Нельзя повторить сохранение: в записи идемпотентности нет временного PDF.",
            technical_message="Record has no temp_scan_path",
            idempotency_key=record.idempotency_key,
            record_path=record_path,
            record=record.to_dict(),
        )

    source_path = Path(record.temp_scan_path)

    logger.info(
        "Idempotent storage retry started operation_id=%s task_id=%s idempotency_key=%s source_path=%s",
        operation_id,
        task_id,
        record.idempotency_key,
        source_path,
    )

    current_record = mark_storing(record_path, record) or record

    try:
        stored_document = store_document(
            source_path=source_path,
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
            settings=storage_settings,
            operation_id=operation_id,
        )
    except StorageError as exc:
        mark_scanned(record_path, current_record, temp_scan_path=source_path)
        mark_failed(
            record_path,
            current_record,
            status="scanned",
            error_code=exc.code,
            operator_message=exc.operator_message,
            technical_message=exc.technical_message,
        )
        raise

    final_record = mark_succeeded(
        record_path,
        current_record,
        final_file_name=stored_document.file_name,
        final_file_path=stored_document.file_path,
    ) or current_record

    result = ProcessedDocument(
        task_id=task_id,
        operation_id=operation_id,
        temp_scan_path=source_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
        idempotency_key=final_record.idempotency_key,
        idempotent_replay=False,
    )

    logger.info(
        "Idempotent storage retry finished operation_id=%s task_id=%s idempotency_key=%s file_path=%s",
        operation_id,
        task_id,
        final_record.idempotency_key,
        result.file_path,
    )

    return result


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
    idempotency_key: str | None = None,
    idempotency_settings: IdempotencySettings | None = None,
) -> ProcessedDocument:
    """
    Полный процесс:

    1. Включаем месячные txt-логи.
    2. Проверяем входные данные для имени.
    3. Проверяем idempotency_key, если он передан.
    4. Захватываем file lock сканера.
    5. Сканируем документ во временный PDF.
    6. Атомарно переносим PDF в архив.
    7. Освобождаем lock.
    8. Возвращаем финальное имя и путь.

    Если idempotency_key уже успешно выполнялся, повторного сканирования не будет.
    """

    task_id_str = str(task_id).strip()
    operation_id = build_operation_id()

    effective_scanner_settings = get_effective_scanner_settings(scanner_settings)
    effective_storage_settings = get_effective_storage_settings(storage_settings)
    effective_idempotency_settings = get_effective_idempotency_settings(
        idempotency_settings,
        effective_scanner_settings,
    )

    configure_monthly_file_logging_from_env(effective_scanner_settings.incoming_dir)

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
        "Document scan process started: operation_id=%s task_id=%s expected_file_name=%s lock_path=%s idempotency_key=%s",
        operation_id,
        task_id_str,
        expected_file_name,
        lock_path,
        idempotency_key,
    )

    idempotency_decision = begin_idempotent_operation(
        idempotency_key=idempotency_key,
        operation_id=operation_id,
        task_id=task_id_str,
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
        expected_file_name=expected_file_name,
        settings=effective_idempotency_settings,
    )

    idempotency_record = idempotency_decision.record
    idempotency_record_path = idempotency_decision.record_path

    if idempotency_decision.mode == "return_existing":
        if idempotency_record is None:
            raise IdempotencyError(
                code="idempotency_record_missing",
                operator_message="Не удалось получить сохранённый результат идемпотентной операции.",
                technical_message="Decision mode return_existing has no record",
                idempotency_key=idempotency_key,
            )

        result = _processed_from_existing_idempotency_record(
            task_id=task_id_str,
            record=idempotency_record,
        )

        logger.info(
            "Document scan process returned existing idempotent result: operation_id=%s task_id=%s idempotency_key=%s file_path=%s",
            operation_id,
            task_id_str,
            idempotency_record.idempotency_key,
            result.file_path,
        )

        return result

    if idempotency_decision.mode == "retry_storage":
        if idempotency_record is None or idempotency_record_path is None:
            raise IdempotencyError(
                code="idempotency_retry_record_missing",
                operator_message="Не удалось повторить сохранение: запись идемпотентности не найдена.",
                technical_message="Decision mode retry_storage has no record or path",
                idempotency_key=idempotency_key,
            )

        return _storage_retry_from_idempotency_record(
            task_id=task_id_str,
            operation_id=operation_id,
            record=idempotency_record,
            record_path=idempotency_record_path,
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
            storage_settings=effective_storage_settings,
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

    temp_scan_path: Path | None = None
    current_record = idempotency_record

    try:
        with lock_context:
            temp_scan_path = scan_document(
                task_id=task_id_str,
                settings=effective_scanner_settings,
                operation_id=operation_id,
            )

            current_record = mark_scanned(
                idempotency_record_path,
                current_record,
                temp_scan_path=temp_scan_path,
            ) or current_record

            current_record = mark_storing(
                idempotency_record_path,
                current_record,
            ) or current_record

            stored_document: StoredDocument = store_document(
                source_path=temp_scan_path,
                doc_type=doc_type,
                document_datetime=document_datetime,
                document_number=document_number,
                settings=effective_storage_settings,
                operation_id=operation_id,
            )

            current_record = mark_succeeded(
                idempotency_record_path,
                current_record,
                final_file_name=stored_document.file_name,
                final_file_path=stored_document.file_path,
            ) or current_record

    except ScannerError as exc:
        status = "failed"
        if exc.code == "scanner_interrupted":
            status = "interrupted"
        elif exc.code == "scanner_timeout":
            status = "timeout"

        mark_failed(
            idempotency_record_path,
            current_record,
            status=status,  # type: ignore[arg-type]
            error_code=exc.code,
            operator_message=exc.operator_message,
            technical_message=exc.technical_message,
        )
        logger.error(
            "Document scan process failed at scanner stage operation_id=%s task_id=%s idempotency_key=%s error_code=%s",
            operation_id,
            task_id_str,
            idempotency_key,
            exc.code,
        )
        raise

    except StorageError as exc:
        # Если скан уже получен, оставляем record в состоянии scanned.
        # Следующий запуск с тем же idempotency_key попробует только storage.
        if temp_scan_path is not None:
            current_record = mark_scanned(
                idempotency_record_path,
                current_record,
                temp_scan_path=temp_scan_path,
            ) or current_record
            mark_failed(
                idempotency_record_path,
                current_record,
                status="scanned",
                error_code=exc.code,
                operator_message=exc.operator_message,
                technical_message=exc.technical_message,
            )
        else:
            mark_failed(
                idempotency_record_path,
                current_record,
                status="failed",
                error_code=exc.code,
                operator_message=exc.operator_message,
                technical_message=exc.technical_message,
            )

        logger.error(
            "Document scan process failed at storage stage operation_id=%s task_id=%s idempotency_key=%s error_code=%s temp_scan_path=%s",
            operation_id,
            task_id_str,
            idempotency_key,
            exc.code,
            temp_scan_path,
        )
        raise

    except Exception as exc:
        mark_failed(
            idempotency_record_path,
            current_record,
            status="failed",
            error_code=type(exc).__name__,
            operator_message="Непредвиденная ошибка при обработке скана.",
            technical_message=str(exc),
        )
        logger.exception(
            "Document scan process failed unexpectedly operation_id=%s task_id=%s idempotency_key=%s",
            operation_id,
            task_id_str,
            idempotency_key,
        )
        raise

    processed_document = ProcessedDocument(
        task_id=task_id_str,
        operation_id=operation_id,
        temp_scan_path=temp_scan_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
        idempotency_key=idempotency_key,
        idempotent_replay=False,
    )

    logger.info(
        "Document scan process finished: operation_id=%s task_id=%s file_name=%s file_path=%s idempotency_key=%s",
        operation_id,
        task_id_str,
        processed_document.file_name,
        processed_document.file_path,
        idempotency_key,
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
    configure_monthly_file_logging_from_env()

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
    idempotency_key: str | None = None,
    idempotency_settings: IdempotencySettings | None = None,
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
            idempotency_key=idempotency_key,
            idempotency_settings=idempotency_settings,
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

    except IdempotencyError as exc:
        return DocumentProcessResult(
            success=False,
            operation_id=fallback_operation_id,
            stage="idempotency",
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
