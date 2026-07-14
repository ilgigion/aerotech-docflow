from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import secrets

from app.naming import NamingError, build_document_filename
from app.scanner import ScannerError, ScannerSettings, scan_document
from app.storage import StorageError, StorageSettings, StoredDocument, build_archive_directory, ensure_archive_directory, store_document


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessedDocument:
    task_id: str
    operation_id: str
    temp_scan_path: Path
    file_name: str
    file_path: Path


@dataclass(frozen=True)
class DocumentProcessResult:
    """
    Единый результат процесса для будущего FastAPI/Planfix.

    success=True:
        file_name и file_path заполнены.

    success=False:
        stage, error_code, operator_message и technical_message объясняют ошибку.
    """

    success: bool
    stage: str
    operation_id: str
    task_id: str
    operator_message: str = ""
    technical_message: str = ""
    error_code: str = ""
    temp_scan_path: Path | None = None
    file_name: str | None = None
    file_path: Path | None = None
    details: dict | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stage": self.stage,
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "error_code": self.error_code,
            "temp_scan_path": str(self.temp_scan_path) if self.temp_scan_path else None,
            "file_name": self.file_name,
            "file_path": str(self.file_path) if self.file_path else None,
            "details": self.details or {},
        }


def build_operation_id() -> str:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)
    return f"SCAN_{now}_{suffix}"


def _error_to_result(
    exc: Exception,
    *,
    stage: str,
    operation_id: str,
    task_id: str,
    temp_scan_path: Path | None = None,
) -> DocumentProcessResult:
    operator_message = "Произошла ошибка обработки документа."
    technical_message = repr(exc)
    error_code = "unknown_error"
    details: dict = {}

    if hasattr(exc, "to_operator_text"):
        operator_message = exc.to_operator_text()  # type: ignore[attr-defined]

    if hasattr(exc, "to_log_dict"):
        details = exc.to_log_dict()  # type: ignore[attr-defined]
        error_code = str(details.get("code") or error_code)
        technical_message = str(details.get("technical_message") or technical_message)

    return DocumentProcessResult(
        success=False,
        stage=stage,
        operation_id=operation_id,
        task_id=task_id,
        operator_message=operator_message,
        technical_message=technical_message,
        error_code=error_code,
        temp_scan_path=temp_scan_path,
        details=details,
    )


def precheck_document_flow(
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    storage_settings: StorageSettings | None = None,
) -> str:
    """
    Простая предварительная проверка до запуска сканера.

    Что проверяем заранее:
    1. Можно ли сформировать имя файла.
    2. Можно ли построить/создать папку архива.

    Это важно: если оператор передал плохие входные данные,
    лучше узнать об этом до физического сканирования.
    """

    if storage_settings is None:
        storage_settings = StorageSettings()

    file_name = build_document_filename(
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
    )

    destination_dir = build_archive_directory(
        archive_root=Path(storage_settings.archive_root),
        doc_type=doc_type,
        document_datetime=document_datetime,
    )

    ensure_archive_directory(
        destination_dir=destination_dir,
        archive_root=Path(storage_settings.archive_root),
    )

    return file_name


def process_document_scan(
    task_id: int | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    *,
    scanner_settings: ScannerSettings | None = None,
    storage_settings: StorageSettings | None = None,
    operation_id: str | None = None,
) -> ProcessedDocument:
    """
    Полный процесс с исключениями.

    Порядок улучшен:
    1. Сначала проверяем имя и архив.
    2. Только потом запускаем сканер.
    3. Потом переносим файл.
    """

    if operation_id is None:
        operation_id = build_operation_id()

    task_id_str = str(task_id).strip()

    logger.info(
        "Document flow started operation_id=%s task_id=%s doc_type=%s document_datetime=%s document_number=%s",
        operation_id,
        task_id_str,
        doc_type,
        document_datetime,
        document_number,
    )

    precheck_document_flow(
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
        storage_settings=storage_settings,
    )

    temp_scan_path = scan_document(
        task_id=task_id_str,
        settings=scanner_settings,
        operation_id=operation_id,
    )

    stored_document: StoredDocument = store_document(
        source_path=temp_scan_path,
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
        settings=storage_settings,
        operation_id=operation_id,
    )

    logger.info(
        "Document flow completed operation_id=%s task_id=%s file_name=%s file_path=%s",
        operation_id,
        task_id_str,
        stored_document.file_name,
        stored_document.file_path,
    )

    return ProcessedDocument(
        task_id=task_id_str,
        operation_id=operation_id,
        temp_scan_path=temp_scan_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
    )


def process_document_scan_safe(
    task_id: int | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    *,
    scanner_settings: ScannerSettings | None = None,
    storage_settings: StorageSettings | None = None,
    operation_id: str | None = None,
) -> DocumentProcessResult:
    """
    Полный процесс без выброса исключений наружу.

    Это удобный формат для будущего API:
    функция всегда возвращает DocumentProcessResult.
    """

    if operation_id is None:
        operation_id = build_operation_id()

    task_id_str = str(task_id).strip()
    temp_scan_path: Path | None = None

    try:
        precheck_document_flow(
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
            storage_settings=storage_settings,
        )
    except NamingError as exc:
        logger.exception("Document flow precheck naming error operation_id=%s", operation_id)
        return _error_to_result(exc, stage="naming", operation_id=operation_id, task_id=task_id_str)
    except StorageError as exc:
        logger.exception("Document flow precheck storage error operation_id=%s", operation_id)
        return _error_to_result(exc, stage="storage_precheck", operation_id=operation_id, task_id=task_id_str)

    try:
        temp_scan_path = scan_document(
            task_id=task_id_str,
            settings=scanner_settings,
            operation_id=operation_id,
        )
    except ScannerError as exc:
        logger.exception("Document flow scanner error operation_id=%s", operation_id)
        return _error_to_result(exc, stage="scanner", operation_id=operation_id, task_id=task_id_str)

    try:
        stored_document = store_document(
            source_path=temp_scan_path,
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
            settings=storage_settings,
            operation_id=operation_id,
        )
    except NamingError as exc:
        logger.exception("Document flow naming error after scan operation_id=%s temp_scan_path=%s", operation_id, temp_scan_path)
        return _error_to_result(exc, stage="naming", operation_id=operation_id, task_id=task_id_str, temp_scan_path=temp_scan_path)
    except StorageError as exc:
        logger.exception("Document flow storage error operation_id=%s temp_scan_path=%s", operation_id, temp_scan_path)
        return _error_to_result(exc, stage="storage", operation_id=operation_id, task_id=task_id_str, temp_scan_path=temp_scan_path)

    return DocumentProcessResult(
        success=True,
        stage="done",
        operation_id=operation_id,
        task_id=task_id_str,
        operator_message="Документ успешно отсканирован и сохранён в архив.",
        temp_scan_path=temp_scan_path,
        file_name=stored_document.file_name,
        file_path=stored_document.file_path,
    )
