from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import json
import logging
import os
import shutil
import socket
import time
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
        reservation_path: Path | None = None,
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.source_path = source_path
        self.destination_path = destination_path
        self.temp_path = temp_path
        self.reservation_path = reservation_path

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
            "reservation_path": str(self.reservation_path) if self.reservation_path else None,
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


class DestinationReservationError(StorageError):
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

    reservation_stale_after_seconds:
        Через сколько секунд .reserve-файл можно считать зависшим.
    """

    archive_root: Path = Path(r"D:\archive_test")
    copy_buffer_size: int = 1024 * 1024
    keep_temp_on_error: bool = False
    reservation_stale_after_seconds: int = 30 * 60


@dataclass(frozen=True)
class StoredDocument:
    """
    Результат переноса файла в архив.
    """

    file_name: str
    file_path: Path


@dataclass(frozen=True)
class DestinationReservation:
    """
    Резервирование финального имени файла.

    destination_path:
        Финальное имя PDF.

    reservation_path:
        Технический .reserve-файл рядом с destination_path.
        Он создаётся атомарно и мешает второму процессу выбрать то же имя.
    """

    destination_path: Path
    reservation_path: Path
    operation_id: str | None


def load_storage_settings_from_env() -> StorageSettings:
    """
    Настройки storage из переменных окружения.
    """

    return StorageSettings(
        archive_root=Path(os.getenv("ARCHIVE_ROOT", r"D:\archive_test")),
        copy_buffer_size=int(os.getenv("STORAGE_COPY_BUFFER_SIZE", str(1024 * 1024))),
        keep_temp_on_error=os.getenv("STORAGE_KEEP_TEMP_ON_ERROR", "0").strip() == "1",
        reservation_stale_after_seconds=int(
            os.getenv("STORAGE_RESERVATION_STALE_AFTER_SECONDS", str(30 * 60))
        ),
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_datetime_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


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
    Проверяем корень архива и создаём папку назначения.
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


def build_reservation_path(destination_path: Path) -> Path:
    """
    Резервный файл для финального PDF.

    Пример:
        УПД_260710_101025_2455B.pdf
        .УПД_260710_101025_2455B.pdf.reserve
    """

    return destination_path.with_name(f".{destination_path.name}.reserve")


def read_reservation_info(reservation_path: Path) -> dict[str, Any] | None:
    if not reservation_path.exists():
        return None

    try:
        return json.loads(reservation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "invalid_reservation_file": True,
            "error": str(exc),
        }


def is_reservation_stale(
    reservation_path: Path,
    stale_after_seconds: int,
) -> bool:
    """
    Старый .reserve можно удалить, чтобы он не блокировал имя навсегда.
    """

    info = read_reservation_info(reservation_path)

    if not info:
        return False

    if info.get("invalid_reservation_file"):
        try:
            age_seconds = time.time() - reservation_path.stat().st_mtime
            return age_seconds >= stale_after_seconds
        except OSError:
            return True

    created_at = parse_datetime_utc(str(info.get("created_at_utc", "")))
    if created_at is None:
        try:
            age_seconds = time.time() - reservation_path.stat().st_mtime
            return age_seconds >= stale_after_seconds
        except OSError:
            return True

    age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    return age_seconds >= stale_after_seconds


def create_reservation_file(
    reservation_path: Path,
    destination_path: Path,
    operation_id: str | None,
) -> None:
    """
    Атомарно создаёт .reserve-файл.

    os.O_CREAT | os.O_EXCL гарантирует:
    если другой процесс уже зарезервировал это имя, текущий процесс получит FileExistsError.
    """

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    reservation_data = {
        "operation_id": operation_id,
        "destination_path": str(destination_path),
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at_utc": utc_now_iso(),
    }

    try:
        fd = os.open(str(reservation_path), flags)
    except FileExistsError:
        raise
    except OSError as exc:
        raise DestinationReservationError(
            code="destination_reservation_create_error",
            operator_message="Не удалось зарезервировать имя файла в архиве.",
            technical_message=str(exc),
            destination_path=destination_path,
            reservation_path=reservation_path,
        ) from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(reservation_data, file, ensure_ascii=False, indent=2)
            file.write("\n")
    except OSError as exc:
        raise DestinationReservationError(
            code="destination_reservation_write_error",
            operator_message="Не удалось записать резервирование имени файла в архиве.",
            technical_message=str(exc),
            destination_path=destination_path,
            reservation_path=reservation_path,
        ) from exc


def reserve_unique_destination_path(
    destination_dir: Path,
    file_name: str,
    settings: StorageSettings,
    *,
    operation_id: str | None = None,
) -> DestinationReservation:
    """
    Безопасно выбирает и резервирует уникальное финальное имя.

    Отличие от простой проверки destination.exists():
    здесь есть атомарный .reserve-файл, который защищает от гонки двух процессов.
    """

    base_destination_path = destination_dir / file_name
    stem = base_destination_path.stem
    suffix = base_destination_path.suffix

    for index in range(0, 100):
        if index == 0:
            candidate = base_destination_path
        else:
            candidate = destination_dir / f"{stem}_{index:02d}{suffix}"

        reservation_path = build_reservation_path(candidate)

        if candidate.exists():
            continue

        if reservation_path.exists():
            if is_reservation_stale(
                reservation_path=reservation_path,
                stale_after_seconds=settings.reservation_stale_after_seconds,
            ):
                logger.warning(
                    "Removing stale destination reservation operation_id=%s reservation_path=%s",
                    operation_id,
                    reservation_path,
                )
                try:
                    reservation_path.unlink(missing_ok=True)
                except OSError:
                    # Если не смогли удалить, просто пробуем следующее имя.
                    continue
            else:
                continue

        try:
            create_reservation_file(
                reservation_path=reservation_path,
                destination_path=candidate,
                operation_id=operation_id,
            )

            logger.info(
                "Destination reserved operation_id=%s destination_path=%s reservation_path=%s",
                operation_id,
                candidate,
                reservation_path,
            )

            return DestinationReservation(
                destination_path=candidate,
                reservation_path=reservation_path,
                operation_id=operation_id,
            )

        except FileExistsError:
            # Другой процесс успел зарезервировать это имя.
            continue

    raise DestinationReservationError(
        code="too_many_duplicates_or_reservations",
        operator_message="В архиве уже слишком много файлов или резервирований с похожим именем.",
        technical_message=f"Could not reserve unique name for: {base_destination_path}",
        destination_path=base_destination_path,
    )


def release_destination_reservation(
    reservation: DestinationReservation,
    *,
    operation_id: str | None = None,
) -> None:
    """
    Удаляет .reserve-файл после успеха или ошибки.
    """

    try:
        reservation.reservation_path.unlink(missing_ok=True)
        logger.info(
            "Destination reservation released operation_id=%s reservation_path=%s",
            operation_id,
            reservation.reservation_path,
        )
    except OSError as exc:
        logger.warning(
            "Failed to release destination reservation operation_id=%s reservation_path=%s error=%s",
            operation_id,
            reservation.reservation_path,
            exc,
        )


def build_atomic_temp_path(destination_path: Path) -> Path:
    """
    Создаёт уникальный путь временного файла рядом с финальным файлом.
    """

    token = uuid.uuid4().hex[:12]
    return destination_path.with_name(f".{destination_path.name}.{token}.tmp")


def copy_file_to_temp(
    source_path: Path,
    temp_path: Path,
    *,
    buffer_size: int,
) -> None:
    """
    Копирует source_path во временный файл temp_path.
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
    Атомарно публикует .tmp как final.pdf без возможности перезаписи.

    temp_path и destination_path находятся в одном каталоге. Создание hard link
    является атомарным и завершается FileExistsError, если финальное имя уже
    занято. Только после успешной публикации удаляется имя временного файла.
    Это устраняет окно между exists-check и os.replace().
    """

    try:
        os.link(str(temp_path), str(destination_path))
    except FileExistsError as exc:
        raise FileMoveError(
            code="destination_appeared_during_atomic_move",
            operator_message="Файл с таким именем появился в архиве во время переноса.",
            technical_message=f"Destination already exists: {destination_path}",
            destination_path=destination_path,
            temp_path=temp_path,
        ) from exc
    except OSError as exc:
        raise FileMoveError(
            code="atomic_no_clobber_finalize_error",
            operator_message=(
                "Не удалось безопасно опубликовать файл в архиве без перезаписи. "
                "Проверьте поддержку hard links файловой системой архива."
            ),
            technical_message=f"No-clobber hard-link publish failed: {exc}",
            destination_path=destination_path,
            temp_path=temp_path,
        ) from exc

    try:
        temp_path.unlink()
    except OSError as exc:
        # Финальный файл уже безопасно опубликован. Не удаляем его при ошибке
        # очистки второго имени того же файла.
        logger.warning(
            "Final file published but atomic temp link cleanup failed "
            "temp_path=%s destination_path=%s error=%s",
            temp_path,
            destination_path,
            exc,
        )


def remove_source_after_success(
    source_path: Path,
    destination_path: Path,
    operation_id: str | None = None,
) -> None:
    """
    Удаляет исходный временный файл после успешной финализации.
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
    reservation: DestinationReservation,
    settings: StorageSettings,
    *,
    operation_id: str | None = None,
) -> None:
    """
    Безопасный перенос файла в архив.

    Схема:
        1. Есть зарезервированный destination_path.
        2. Копируем source во временный .tmp рядом с destination_path.
        3. Проверяем размер и PDF-заголовок .tmp.
        4. Переименовываем .tmp в destination_path.
        5. Удаляем source из incoming.
    """

    destination_path = reservation.destination_path
    temp_path = build_atomic_temp_path(destination_path)

    logger.info(
        "Atomic move started operation_id=%s source_path=%s temp_path=%s destination_path=%s reservation_path=%s",
        operation_id,
        source_path,
        temp_path,
        destination_path,
        reservation.reservation_path,
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
    on_destination_reserved: Callable[[Path], None] | None = None,
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

    Внутри:
        1. формируется имя;
        2. резервируется уникальный destination_path через .reserve;
        3. выполняется атомарный перенос через .tmp.
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

    reservation = reserve_unique_destination_path(
        destination_dir=destination_dir,
        file_name=file_name,
        settings=settings,
        operation_id=operation_id,
    )

    try:
        if on_destination_reserved is not None:
            on_destination_reserved(reservation.destination_path)

        atomic_move_file(
            source_path=source_path,
            reservation=reservation,
            settings=settings,
            operation_id=operation_id,
        )

    finally:
        release_destination_reservation(
            reservation=reservation,
            operation_id=operation_id,
        )

    stored_document = StoredDocument(
        file_name=reservation.destination_path.name,
        file_path=reservation.destination_path,
    )

    logger.info(
        "Store document completed operation_id=%s file_name=%s file_path=%s",
        operation_id,
        stored_document.file_name,
        stored_document.file_path,
    )

    return stored_document
