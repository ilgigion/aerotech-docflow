from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import shutil

from app.naming import (
    NamingError,
    build_document_filename,
    normalize_doc_type,
    parse_document_datetime,
)


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


class ArchiveRootMissingError(StorageError):
    pass


class FileMoveError(StorageError):
    pass


@dataclass(frozen=True)
class StorageSettings:
    """
    Настройки архива.

    archive_root — корневая папка архива.

    Пример:
        D:\\archive_test

    Тогда итоговый путь будет:
        D:\\archive_test\\2026\\УПД\\УПД_260710_101025_2455B.pdf
    """

    archive_root: Path = Path(r"D:\archive_test")


@dataclass(frozen=True)
class StoredDocument:
    """
    Результат переноса файла в архив.
    """

    file_name: str
    file_path: Path


def load_storage_settings_from_env() -> StorageSettings:
    """
    Позже будем брать путь архива из .env.

    Сейчас можно передавать StorageSettings вручную.
    """

    return StorageSettings(
        archive_root=Path(os.getenv("ARCHIVE_ROOT", r"D:\archive_test"))
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


def build_archive_directory(
    archive_root: Path,
    doc_type: str,
    document_datetime: datetime | str,
) -> Path:
    """
    Формирует папку назначения:

        archive_root / ГОД / ТИП

    Пример:

        D:\\archive_test\\2026\\УПД
    """

    parsed_datetime = parse_document_datetime(document_datetime)
    normalized_doc_type = normalize_doc_type(doc_type)

    year = parsed_datetime.strftime("%Y")

    return archive_root / year / normalized_doc_type


def ensure_archive_directory(destination_dir: Path, archive_root: Path) -> None:
    """
    Проверяем корень архива и автоматически создаём папку назначения:

        archive_root / ГОД / ТИП

    Например:

        D:\\archive_test\\2026\\УПД
    """

    if archive_root.exists() and not archive_root.is_dir():
        raise ArchiveRootMissingError(
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
        raise FileMoveError(
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


def move_file(source_path: Path, destination_path: Path) -> None:
    """
    Переносим файл.

    shutil.move работает и внутри одного диска, и между разными дисками.
    """

    try:
        shutil.move(str(source_path), str(destination_path))

    except OSError as exc:
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

    validate_source_file(source_path)

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

    move_file(
        source_path=source_path,
        destination_path=destination_path,
    )

    return StoredDocument(
        file_name=destination_path.name,
        file_path=destination_path,
    )