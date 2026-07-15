from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import os
import shutil
import uuid

from app.naming import (
    build_document_filename,
    normalize_doc_type,
    parse_document_datetime,
)


logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """
    Базовая ошибка переноса файла в архив.
    """

    def __init__(
        self,
        code: str,
        operator_message: str,
        technical_message: str = "",
        source_path: Path | None = None,
        destination_path: Path | None = None,
        temp_path: Path | None = None,
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.source_path = source_path
        self.destination_path = destination_path
        self.temp_path = temp_path

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "source_path": str(self.source_path) if self.source_path else None,
            "destination_path": str(self.destination_path) if self.destination_path else None,
            "temp_path": str(self.temp_path) if self.temp_path else None,
        }


class SourceFileMissingError(StorageError):
    pass


class SourcePathNotFileError(StorageError):
    pass


class SourceFileInvalidError(StorageError):
    pass


class ArchiveRootError(StorageError):
    pass


class ArchiveDirectoryCreateError(StorageError):
    pass


class FileMoveError(StorageError):
    pass


@dataclass(frozen=True)
class StorageSettings:
    """
    Настройки архива.

    archive_root:
        Корневая папка архива.

    copy_buffer_size:
        Размер блока при копировании файла во временный .tmp.

    keep_temp_on_error:
        Если True, при ошибке временный .tmp-файл не удаляется.
        Это удобно только для диагностики.
    """

    archive_root: Path = Path(r"D:\archive_test")
    copy_buffer_size: int = 1024 * 1024
    keep_temp_on_error: bool = False


@dataclass(frozen=True)
class StoredDocument:
    """
    Результат переноса файла в архив.
    """

    file_name: str
    file_path: Path


def load_storage_settings_from_env() -> StorageSettings:
    """
    Настройки storage из переменных окружения.
    """

    return StorageSettings(
        archive_root=Path(os.getenv("ARCHIVE_ROOT", r"D:\archive_test")),
        copy_buffer_size=int(os.getenv("STORAGE_COPY_BUFFER_SIZE", str(1024 * 1024))),
        keep_temp_on_error=os.getenv("STORAGE_KEEP_TEMP_ON_ERROR", "0").strip() == "1",
    )


def validate_source_file(source_path: Path) -> None:
    """
    Проверяем, что временный PDF существует.
    """

    if not source_path.exists():
        raise SourceFileMissingError(
            code="source_file_missing",
            operator_message="Временный файл скана не найден.",
            technical_message=f"Source file does not exist: {source_path}",
            source_path=source_path,
        )

    if not source_path.is_file():
        raise SourcePathNotFileError(
            code="source_path_not_file",
            operator_message="Путь временного скана некорректен.",
            technical_message=f"Source path is not a file: {source_path}",
            source_path=source_path,
        )


def validate_pdf_file(path: Path, *, min_size_bytes: int = 5) -> None:
    """
    Базовая проверка PDF.

    Проверяем:
    - файл существует;
    - файл не пустой;
    - заголовок начинается с %PDF-.
    """

    if not path.exists():
        raise SourceFileInvalidError(
            code="pdf_file_missing",
            operator_message="PDF-файл не найден.",
            technical_message=f"PDF file does not exist: {path}",
            source_path=path,
        )

    if not path.is_file():
        raise SourceFileInvalidError(
            code="pdf_path_not_file",
            operator_message="Путь PDF некорректен.",
            technical_message=f"PDF path is not a file: {path}",
            source_path=path,
        )

    file_size = path.stat().st_size

    if file_size < min_size_bytes:
        raise SourceFileInvalidError(
            code="pdf_file_too_small",
            operator_message="PDF-файл слишком маленький. Возможно, сканирование прошло некорректно.",
            technical_message=f"PDF file too small: {file_size} bytes",
            source_path=path,
        )

    with path.open("rb") as file:
        header = file.read(5)

    if header != b"%PDF-":
        raise SourceFileInvalidError(
            code="pdf_file_invalid_header",
            operator_message="Файл скана создан, но это не PDF.",
            technical_message=f"Invalid PDF header: {header!r}",
            source_path=path,
        )


def build_archive_directory(
    archive_root: Path,
    doc_type: str,
    document_datetime: datetime | str,
) -> Path:
    """
    Формирует папку назначения:

        archive_root / ГОД / ТИП
    """

    parsed_datetime = parse_document_datetime(document_datetime)
    normalized_doc_type = normalize_doc_type(doc_type)

    year = parsed_datetime.strftime("%Y")

    return archive_root / year / normalized_doc_type


def ensure_archive_directory(destination_dir: Path, archive_root: Path) -> None:
    """
    Проверяем корень архива и автоматически создаём папку назначения:

        archive_root / ГОД / ТИП
    """

    if archive_root.exists() and not archive_root.is_dir():
        raise ArchiveRootError(
            code="archive_root_not_directory",
            operator_message="Путь архива некорректен.",
            technical_message=f"Archive root is not a directory: {archive_root}",
            destination_path=archive_root,
        )

    try:
        destination_dir.mkdir(parents=True, exist_ok=True)

    except OSError as exc:
        raise ArchiveDirectoryCreateError(
            code="archive_directory_create_error",
            operator_message="Не удалось создать папку в архиве.",
            technical_message=str(exc),
            destination_path=destination_dir,
        ) from exc

    if not destination_dir.is_dir():
        raise ArchiveDirectoryCreateError(
            code="archive_destination_not_directory",
            operator_message="Путь назначения в архиве некорректен.",
            technical_message=f"Destination path is not a directory: {destination_dir}",
            destination_path=destination_dir,
        )


def build_unique_destination_path(destination_dir: Path, file_name: str) -> Path:
    """
    Если файл с таким именем уже есть, добавляем суффикс:

        УПД_260710_101025_2455B.pdf
        УПД_260710_101025_2455B_01.pdf
        УПД_260710_101025_2455B_02.pdf

    Параллельный доступ закрывается scanner file lock в document_flow.py.
    """

    destination_path = destination_dir / file_name

    if not destination_path.exists():
        return destination_path

    stem = destination_path.stem
    suffix = destination_path.suffix

    for index in range(1, 100):
        candidate = destination_dir / f"{stem}_{index:02d}{suffix}"

        if not candidate.exists():
            return candidate

    raise FileMoveError(
        code="too_many_duplicates",
        operator_message="В архиве уже слишком много файлов с похожим именем.",
        technical_message=f"Could not build unique name for: {destination_path}",
        destination_path=destination_path,
    )


def build_atomic_temp_path(destination_path: Path) -> Path:
    """
    Создаёт уникальный путь временного файла рядом с финальным файлом.

    Пример:
        УПД_260710_101025_2455B.pdf
        .УПД_260710_101025_2455B.pdf.8f3a1c2b9a11.tmp
    """

    token = uuid.uuid4().hex[:12]

    return destination_path.with_name(
        f".{destination_path.name}.{token}.tmp"
    )


def copy_file_to_temp(
    source_path: Path,
    temp_path: Path,
    *,
    buffer_size: int,
) -> None:
    """
    Копирует source_path во временный файл temp_path.

    Открываем temp_path в режиме xb:
        создать только если файла ещё нет.
    """

    try:
        with source_path.open("rb") as source_file:
            with temp_path.open("xb") as temp_file:
                shutil.copyfileobj(
                    fsrc=source_file,
                    fdst=temp_file,
                    length=buffer_size,
                )

                temp_file.flush()
                os.fsync(temp_file.fileno())

    except OSError as exc:
        raise FileMoveError(
            code="atomic_temp_copy_error",
            operator_message="Не удалось скопировать файл во временный файл архива.",
            technical_message=str(exc),
            source_path=source_path,
            temp_path=temp_path,
        ) from exc


def verify_copied_file(
    source_path: Path,
    temp_path: Path,
) -> None:
    """
    Проверяет, что временная копия соответствует исходному файлу по размеру
    и похожа на PDF.
    """

    try:
        source_size = source_path.stat().st_size
        temp_size = temp_path.stat().st_size

    except OSError as exc:
        raise FileMoveError(
            code="atomic_temp_verify_stat_error",
            operator_message="Не удалось проверить временный файл архива.",
            technical_message=str(exc),
            source_path=source_path,
            temp_path=temp_path,
        ) from exc

    if source_size != temp_size:
        raise FileMoveError(
            code="atomic_temp_size_mismatch",
            operator_message="Файл был скопирован в архив не полностью.",
            technical_message=f"Source size={source_size}, temp size={temp_size}",
            source_path=source_path,
            temp_path=temp_path,
        )

    try:
        with temp_path.open("rb") as file:
            header = file.read(5)

    except OSError as exc:
        raise FileMoveError(
            code="atomic_temp_verify_read_error",
            operator_message="Не удалось проверить временный файл архива.",
            technical_message=str(exc),
            source_path=source_path,
            temp_path=temp_path,
        ) from exc

    if header != b"%PDF-":
        raise FileMoveError(
            code="atomic_temp_not_pdf",
            operator_message="Временный файл архива не является PDF.",
            technical_message=f"Invalid temp PDF header: {header!r}",
            source_path=source_path,
            temp_path=temp_path,
        )


def finalize_atomic_move(
    temp_path: Path,
    destination_path: Path,
) -> None:
    """
    Финализирует перенос:
        .tmp -> final.pdf

    В обычном процессе перезаписи быть не должно, потому что:
        - build_unique_destination_path выбрал свободное имя;
        - document_flow держит scanner lock.
    """

    try:
        if destination_path.exists():
            raise FileMoveError(
                code="destination_appeared_during_atomic_move",
                operator_message="Файл с таким именем появился в архиве во время переноса.",
                technical_message=f"Destination already exists: {destination_path}",
                destination_path=destination_path,
                temp_path=temp_path,
            )

        os.replace(str(temp_path), str(destination_path))

    except FileMoveError:
        raise

    except OSError as exc:
        raise FileMoveError(
            code="atomic_finalize_error",
            operator_message="Не удалось завершить перенос файла в архив.",
            technical_message=str(exc),
            destination_path=destination_path,
            temp_path=temp_path,
        ) from exc


def remove_source_after_success(
    source_path: Path,
    destination_path: Path,
    operation_id: str | None = None,
) -> None:
    """
    Удаляет исходный временный файл после успешной финализации.

    Если удалить не удалось, финальный архивный файл уже существует.
    Поэтому не превращаем операцию в ошибку, а пишем warning.
    """

    try:
        source_path.unlink(missing_ok=True)

    except OSError as exc:
        logger.warning(
            "Final file exists, but source cleanup failed operation_id=%s source_path=%s destination_path=%s error=%s",
            operation_id,
            source_path,
            destination_path,
            exc,
        )


def cleanup_temp_file(
    temp_path: Path,
    *,
    keep_temp_on_error: bool,
    operation_id: str | None = None,
) -> None:
    """
    Удаляет .tmp после ошибки.
    """

    if keep_temp_on_error:
        logger.warning(
            "Keeping atomic temp file for diagnostics operation_id=%s temp_path=%s",
            operation_id,
            temp_path,
        )
        return

    try:
        temp_path.unlink(missing_ok=True)

    except OSError as exc:
        logger.warning(
            "Failed to cleanup atomic temp file operation_id=%s temp_path=%s error=%s",
            operation_id,
            temp_path,
            exc,
        )


def atomic_move_file(
    source_path: Path,
    destination_path: Path,
    settings: StorageSettings,
    *,
    operation_id: str | None = None,
) -> None:
    """
    Безопасный перенос файла в архив.

    Схема:
        1. Проверяем source PDF.
        2. Копируем source во временный .tmp рядом с final.pdf.
        3. Проверяем размер временной копии.
        4. Атомарно переименовываем .tmp в final.pdf.
        5. Удаляем source из incoming.

    Если ошибка случилась до финального переименования:
        - source остаётся на месте;
        - .tmp удаляется, если keep_temp_on_error=False.
    """

    temp_path = build_atomic_temp_path(destination_path)

    logger.info(
        "Atomic move started operation_id=%s source_path=%s temp_path=%s destination_path=%s",
        operation_id,
        source_path,
        temp_path,
        destination_path,
    )

    try:
        validate_pdf_file(source_path)

        copy_file_to_temp(
            source_path=source_path,
            temp_path=temp_path,
            buffer_size=settings.copy_buffer_size,
        )

        verify_copied_file(
            source_path=source_path,
            temp_path=temp_path,
        )

        finalize_atomic_move(
            temp_path=temp_path,
            destination_path=destination_path,
        )

        remove_source_after_success(
            source_path=source_path,
            destination_path=destination_path,
            operation_id=operation_id,
        )

        logger.info(
            "Atomic move completed operation_id=%s destination_path=%s",
            operation_id,
            destination_path,
        )

    except Exception:
        cleanup_temp_file(
            temp_path=temp_path,
            keep_temp_on_error=settings.keep_temp_on_error,
            operation_id=operation_id,
        )
        raise


def store_document(
    source_path: Path | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    settings: StorageSettings | None = None,
    *,
    operation_id: str | None = None,
) -> StoredDocument:
    """
    Главная функция storage.py.

    Внутри используется безопасный перенос:
        copy -> verify -> atomic rename -> cleanup source.
    """

    if settings is None:
        settings = load_storage_settings_from_env()

    source_path = Path(source_path)

    logger.info(
        "Store document requested operation_id=%s source_path=%s doc_type=%s document_datetime=%s document_number=%s archive_root=%s",
        operation_id,
        source_path,
        doc_type,
        document_datetime,
        document_number,
        settings.archive_root,
    )

    validate_source_file(source_path)
    validate_pdf_file(source_path)

    file_name = build_document_filename(
        doc_type=doc_type,
        document_datetime=document_datetime,
        document_number=document_number,
    )

    destination_dir = build_archive_directory(
        archive_root=settings.archive_root,
        doc_type=doc_type,
        document_datetime=document_datetime,
    )

    ensure_archive_directory(
        destination_dir=destination_dir,
        archive_root=settings.archive_root,
    )

    destination_path = build_unique_destination_path(
        destination_dir=destination_dir,
        file_name=file_name,
    )

    atomic_move_file(
        source_path=source_path,
        destination_path=destination_path,
        settings=settings,
        operation_id=operation_id,
    )

    stored_document = StoredDocument(
        file_name=destination_path.name,
        file_path=destination_path,
    )

    logger.info(
        "Store document completed operation_id=%s file_name=%s file_path=%s",
        operation_id,
        stored_document.file_name,
        stored_document.file_path,
    )

    return stored_document
