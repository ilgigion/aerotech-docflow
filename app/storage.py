from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import os
import shutil

from app.naming import build_document_filename, normalize_doc_type, parse_document_datetime
from app.scanner import EnvironmentCheck


logger = logging.getLogger(__name__)

MAX_FULL_PATH_LENGTH_WARNING = 240


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
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.source_path = source_path
        self.destination_path = destination_path

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "source_path": str(self.source_path) if self.source_path else None,
            "destination_path": str(self.destination_path) if self.destination_path else None,
        }


class SourceFileMissingError(StorageError):
    pass


class SourcePathNotFileError(StorageError):
    pass


class ArchiveRootError(StorageError):
    pass


class FileMoveError(StorageError):
    pass


class DestinationPathError(StorageError):
    pass


@dataclass(frozen=True)
class StorageSettings:
    """
    archive_root — корневая папка архива.

    Пример:
        D:\archive_test

    Итоговый путь:
        D:\archive_test\2026\УПД\УПД_260710_101025_2455B.pdf
    """

    archive_root: Path = Path(r"D:\archive_test")


@dataclass(frozen=True)
class StoredDocument:
    file_name: str
    file_path: Path


def load_storage_settings_from_env() -> StorageSettings:
    return StorageSettings(
        archive_root=Path(os.getenv("ARCHIVE_ROOT", r"D:\archive_test"))
    )


def validate_source_file(source_path: Path) -> None:
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


def build_archive_directory(
    archive_root: Path,
    doc_type: str,
    document_datetime: datetime | str,
) -> Path:
    parsed_datetime = parse_document_datetime(document_datetime)
    normalized_doc_type = normalize_doc_type(doc_type)

    year = parsed_datetime.strftime("%Y")

    return Path(archive_root) / year / normalized_doc_type


def ensure_archive_directory(destination_dir: Path, archive_root: Path) -> None:
    """
    Проверяет корень архива и автоматически создаёт папку назначения:

        archive_root / ГОД / ТИП

    По текущему решению archive_root тоже создаётся автоматически.
    Для боевого режима позже можно сделать строже: корень должен существовать заранее.
    """

    archive_root = Path(archive_root)
    destination_dir = Path(destination_dir)

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
        raise FileMoveError(
            code="archive_directory_create_error",
            operator_message="Не удалось создать папку в архиве.",
            technical_message=str(exc),
            destination_path=destination_dir,
        ) from exc

    if not destination_dir.is_dir():
        raise DestinationPathError(
            code="archive_destination_not_directory",
            operator_message="Путь назначения в архиве некорректен.",
            technical_message=f"Destination path is not a directory: {destination_dir}",
            destination_path=destination_dir,
        )

    try:
        test_file = destination_dir / ".archive_write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except OSError as exc:
        raise FileMoveError(
            code="archive_directory_not_writable",
            operator_message="Нет доступа на запись в папку архива.",
            technical_message=str(exc),
            destination_path=destination_dir,
        ) from exc


def check_storage_environment(settings: StorageSettings) -> list[EnvironmentCheck]:
    """
    Диагностика архива без переноса документа.
    """

    checks: list[EnvironmentCheck] = []
    archive_root = Path(settings.archive_root)

    if archive_root.exists() and not archive_root.is_dir():
        checks.append(
            EnvironmentCheck(
                "archive_root",
                False,
                "Путь архива существует, но это не папка",
                str(archive_root),
            )
        )
        return checks

    try:
        archive_root.mkdir(parents=True, exist_ok=True)
        test_file = archive_root / ".archive_root_write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        checks.append(EnvironmentCheck("archive_root", True, "Корневая папка архива доступна", str(archive_root)))
    except OSError as exc:
        checks.append(EnvironmentCheck("archive_root", False, "Корневая папка архива недоступна", str(exc)))

    return checks


def build_unique_destination_path(destination_dir: Path, file_name: str) -> Path:
    destination_path = Path(destination_dir) / file_name

    if len(str(destination_path)) > MAX_FULL_PATH_LENGTH_WARNING:
        logger.warning(
            "Destination path is long length=%s path=%s",
            len(str(destination_path)),
            destination_path,
        )

    if not destination_path.exists():
        return destination_path

    stem = destination_path.stem
    suffix = destination_path.suffix

    for index in range(1, 100):
        candidate = Path(destination_dir) / f"{stem}_{index:02d}{suffix}"

        if not candidate.exists():
            return candidate

    raise FileMoveError(
        code="too_many_duplicates",
        operator_message="В архиве уже слишком много файлов с похожим именем.",
        technical_message=f"Could not build unique name for: {destination_path}",
        destination_path=destination_path,
    )


def move_file(source_path: Path, destination_path: Path, operation_id: str | None = None) -> None:
    """
    Переносит файл.

    Пока используем shutil.move — это простая версия.
    Более безопасный .tmp-перенос добавим отдельным средним улучшением.
    """

    logger.info(
        "Moving file operation_id=%s source_path=%s destination_path=%s",
        operation_id,
        source_path,
        destination_path,
    )

    try:
        shutil.move(str(source_path), str(destination_path))
    except OSError as exc:
        logger.exception(
            "File move failed operation_id=%s source_path=%s destination_path=%s",
            operation_id,
            source_path,
            destination_path,
        )

        raise FileMoveError(
            code="file_move_error",
            operator_message="Не удалось перенести файл в архив.",
            technical_message=str(exc),
            source_path=source_path,
            destination_path=destination_path,
        ) from exc


def store_document(
    source_path: Path | str,
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
    settings: StorageSettings | None = None,
    operation_id: str | None = None,
) -> StoredDocument:
    """
    Главная функция storage.py.

    На вход:
        source_path         — путь к временному PDF
        doc_type            — тип документа
        document_datetime   — дата/время документа
        document_number     — номер документа

    На выход:
        StoredDocument(file_name, file_path)
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

    try:
        validate_source_file(source_path)

        file_name = build_document_filename(
            doc_type=doc_type,
            document_datetime=document_datetime,
            document_number=document_number,
        )

        destination_dir = build_archive_directory(
            archive_root=Path(settings.archive_root),
            doc_type=doc_type,
            document_datetime=document_datetime,
        )

        ensure_archive_directory(
            destination_dir=destination_dir,
            archive_root=Path(settings.archive_root),
        )

        destination_path = build_unique_destination_path(
            destination_dir=destination_dir,
            file_name=file_name,
        )

        move_file(
            source_path=source_path,
            destination_path=destination_path,
            operation_id=operation_id,
        )

        logger.info(
            "Store document completed operation_id=%s file_name=%s file_path=%s",
            operation_id,
            destination_path.name,
            destination_path,
        )

        return StoredDocument(
            file_name=destination_path.name,
            file_path=destination_path,
        )

    except StorageError as exc:
        # Важное улучшение для сценария 3.2:
        # если сканирование уже создало временный PDF, но архив недоступен,
        # ошибка должна содержать source_path. Тогда оператор/Planfix смогут
        # показать путь к сохранённому временному файлу и повторить только перенос
        # без повторного сканирования.
        if exc.source_path is None:
            exc.source_path = source_path

        logger.error(
            "Store document failed operation_id=%s source_path=%s error=%s",
            operation_id,
            source_path,
            exc.to_log_dict(),
        )

        raise
