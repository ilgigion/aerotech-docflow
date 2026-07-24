from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import logging
import os
import shutil
import time


logger = logging.getLogger(__name__)


CleanupAction = Literal["dry_run", "quarantine"]


class IncomingCleanupError(RuntimeError):
    """
    Базовая ошибка контроля временной папки сканов.
    """

    def __init__(
        self,
        code: str,
        operator_message: str,
        technical_message: str = "",
        path: Path | None = None,
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.path = path

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "path": str(self.path) if self.path else None,
        }


class IncomingDirectoryError(IncomingCleanupError):
    pass


class QuarantineDirectoryError(IncomingCleanupError):
    pass


class QuarantineMoveError(IncomingCleanupError):
    pass


@dataclass(frozen=True)
class IncomingCleanupSettings:
    """
    Настройки контроля временной папки.

    incoming_dir:
        Папка, куда scanner.py сохраняет временные PDF.

    quarantine_dir_name:
        Подпапка внутри incoming_dir, куда переносим старые наши PDF.

    managed_prefix / managed_suffix:
        Признак файлов, созданных нашей системой.
        По текущему scanner.py это PF_*.pdf.

    min_age_seconds:
        Минимальный возраст файла для карантина.
        По умолчанию 24 часа. Это защищает от переноса файла,
        который только что создался или ещё участвует в операции.

    skip_if_lock_exists:
        Если .scanner.lock существует, cleanup ничего не делает.
        Это защита от уборки во время активного сканирования.

    stable_checks / stable_interval_seconds:
        Дополнительная проверка, что размер файла не меняется.
    """

    incoming_dir: Path
    quarantine_dir_name: str = "_failed"
    managed_prefix: str = "PF_"
    managed_suffix: str = ".pdf"
    min_age_seconds: int = 24 * 60 * 60
    lock_file: Path | None = None
    skip_if_lock_exists: bool = True
    stable_checks: int = 2
    stable_interval_seconds: float = 0.2


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_incoming_cleanup_settings_from_env() -> IncomingCleanupSettings:
    incoming_dir = os.getenv("SCANNER_INCOMING_DIR", "").strip()
    if not incoming_dir:
        raise ValueError(
            "SCANNER_INCOMING_DIR is empty; set scanner.incoming_dir in config.toml"
        )
    return IncomingCleanupSettings(
        incoming_dir=Path(incoming_dir),
        quarantine_dir_name=os.getenv(
            "INCOMING_CLEANUP_QUARANTINE_DIR_NAME", "_failed"
        ),
        managed_prefix=os.getenv("INCOMING_CLEANUP_MANAGED_PREFIX", "PF_"),
        managed_suffix=os.getenv("INCOMING_CLEANUP_MANAGED_SUFFIX", ".pdf"),
        min_age_seconds=int(os.getenv("INCOMING_CLEANUP_MIN_AGE_SECONDS", "86400")),
        skip_if_lock_exists=_env_flag("INCOMING_CLEANUP_SKIP_IF_LOCK_EXISTS", True),
        stable_checks=int(os.getenv("INCOMING_CLEANUP_STABLE_CHECKS", "2")),
        stable_interval_seconds=float(
            os.getenv("INCOMING_CLEANUP_STABLE_INTERVAL_SECONDS", "0.2")
        ),
    )


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    size_bytes: int
    modified_at: datetime
    age_seconds: float


@dataclass(frozen=True)
class QuarantinedFile:
    source_path: Path
    destination_path: Path
    size_bytes: int


@dataclass(frozen=True)
class CleanupFileError:
    path: Path
    code: str
    message: str


@dataclass(frozen=True)
class IncomingCleanupResult:
    action: CleanupAction
    incoming_dir: Path
    quarantine_dir: Path
    skipped: bool = False
    skipped_reason: str | None = None
    candidates: list[CleanupCandidate] = field(default_factory=list)
    quarantined_files: list[QuarantinedFile] = field(default_factory=list)
    file_errors: list[CleanupFileError] = field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def quarantined_count(self) -> int:
        return len(self.quarantined_files)

    @property
    def error_count(self) -> int:
        return len(self.file_errors)



def utc_now() -> datetime:
    return datetime.now(timezone.utc)



def get_lock_path(settings: IncomingCleanupSettings) -> Path:
    if settings.lock_file:
        return Path(settings.lock_file)

    return Path(settings.incoming_dir) / ".scanner.lock"



def get_quarantine_root(settings: IncomingCleanupSettings) -> Path:
    return Path(settings.incoming_dir) / settings.quarantine_dir_name



def build_quarantine_run_dir(
    settings: IncomingCleanupSettings,
    run_datetime: datetime | None = None,
) -> Path:
    """
    Для каждого запуска создаём отдельную папку карантина.

    Пример:
        <incoming>\\_failed\\20260715_103012
    """

    if run_datetime is None:
        run_datetime = datetime.now()

    run_id = run_datetime.strftime("%Y%m%d_%H%M%S")

    return get_quarantine_root(settings) / run_id



def ensure_incoming_dir(settings: IncomingCleanupSettings) -> None:
    incoming_dir = Path(settings.incoming_dir)

    if not incoming_dir.exists():
        raise IncomingDirectoryError(
            code="incoming_dir_missing",
            operator_message="Временная папка сканирования не найдена.",
            technical_message=f"Incoming dir does not exist: {incoming_dir}",
            path=incoming_dir,
        )

    if not incoming_dir.is_dir():
        raise IncomingDirectoryError(
            code="incoming_dir_not_directory",
            operator_message="Путь временной папки сканирования некорректен.",
            technical_message=f"Incoming path is not a directory: {incoming_dir}",
            path=incoming_dir,
        )



def ensure_quarantine_dir(quarantine_dir: Path) -> None:
    try:
        quarantine_dir.mkdir(parents=True, exist_ok=True)

    except OSError as exc:
        raise QuarantineDirectoryError(
            code="quarantine_dir_create_error",
            operator_message="Не удалось создать папку карантина для временных сканов.",
            technical_message=str(exc),
            path=quarantine_dir,
        ) from exc

    if not quarantine_dir.is_dir():
        raise QuarantineDirectoryError(
            code="quarantine_path_not_directory",
            operator_message="Путь карантина временных сканов некорректен.",
            technical_message=f"Quarantine path is not a directory: {quarantine_dir}",
            path=quarantine_dir,
        )



def is_managed_incoming_pdf(path: Path, settings: IncomingCleanupSettings) -> bool:
    """
    Определяет, является ли файл нашим временным PDF.

    Важно:
        Не трогаем ручные сканы и любые неизвестные файлы.
        Только PF_*.pdf в корне incoming_dir.
    """

    if not path.is_file():
        return False

    name = path.name

    if not name.startswith(settings.managed_prefix):
        return False

    if not name.lower().endswith(settings.managed_suffix.lower()):
        return False

    return True



def get_file_modified_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)



def get_file_age_seconds(path: Path, now: datetime | None = None) -> float:
    if now is None:
        now = utc_now()

    modified_at = get_file_modified_at(path)

    return (now - modified_at).total_seconds()



def is_old_enough(
    path: Path,
    settings: IncomingCleanupSettings,
    now: datetime | None = None,
) -> bool:
    return get_file_age_seconds(path, now=now) >= settings.min_age_seconds



def is_file_stable(
    path: Path,
    stable_checks: int,
    stable_interval_seconds: float,
) -> bool:
    """
    Проверяет, что размер файла не меняется.

    Для старых файлов обычно это всегда True, но проверка защищает
    от редких случаев, когда файл ещё дописывается.
    """

    if stable_checks <= 0:
        return True

    last_size: int | None = None
    stable_count = 0

    for _ in range(stable_checks + 1):
        if not path.exists() or not path.is_file():
            return False

        current_size = path.stat().st_size

        if current_size == last_size:
            stable_count += 1

            if stable_count >= stable_checks:
                return True
        else:
            stable_count = 0
            last_size = current_size

        time.sleep(stable_interval_seconds)

    return False



def collect_stale_incoming_files(
    settings: IncomingCleanupSettings,
    *,
    now: datetime | None = None,
) -> list[CleanupCandidate]:
    """
    Собирает старые PF_*.pdf в корне incoming_dir.
    """

    ensure_incoming_dir(settings)

    if now is None:
        now = utc_now()

    candidates: list[CleanupCandidate] = []

    for path in sorted(Path(settings.incoming_dir).iterdir()):
        if not is_managed_incoming_pdf(path, settings):
            continue

        if not is_old_enough(path, settings, now=now):
            continue

        if not is_file_stable(
            path=path,
            stable_checks=settings.stable_checks,
            stable_interval_seconds=settings.stable_interval_seconds,
        ):
            logger.warning("Incoming file is not stable, skipping: %s", path)
            continue

        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        age_seconds = (now - modified_at).total_seconds()

        candidates.append(
            CleanupCandidate(
                path=path,
                size_bytes=stat.st_size,
                modified_at=modified_at,
                age_seconds=age_seconds,
            )
        )

    return candidates



def build_unique_destination_path(destination_dir: Path, source_name: str) -> Path:
    destination_path = destination_dir / source_name

    if not destination_path.exists():
        return destination_path

    stem = destination_path.stem
    suffix = destination_path.suffix

    for index in range(1, 1000):
        candidate = destination_dir / f"{stem}_{index:03d}{suffix}"

        if not candidate.exists():
            return candidate

    raise QuarantineMoveError(
        code="quarantine_too_many_duplicates",
        operator_message="В карантине уже слишком много файлов с похожим именем.",
        technical_message=f"Could not build unique quarantine path for: {destination_path}",
        path=destination_path,
    )



def quarantine_file(
    candidate: CleanupCandidate,
    quarantine_dir: Path,
) -> QuarantinedFile:
    destination_path = build_unique_destination_path(
        destination_dir=quarantine_dir,
        source_name=candidate.path.name,
    )

    try:
        shutil.move(str(candidate.path), str(destination_path))

    except OSError as exc:
        raise QuarantineMoveError(
            code="quarantine_move_error",
            operator_message="Не удалось перенести старый временный скан в карантин.",
            technical_message=str(exc),
            path=candidate.path,
        ) from exc

    return QuarantinedFile(
        source_path=candidate.path,
        destination_path=destination_path,
        size_bytes=candidate.size_bytes,
    )



def cleanup_incoming_folder(
    settings: IncomingCleanupSettings | None = None,
    *,
    action: CleanupAction = "dry_run",
) -> IncomingCleanupResult:
    """
    Главная функция контроля временной папки.

    action="dry_run":
        только показать кандидатов, ничего не переносить.

    action="quarantine":
        перенести старые PF_*.pdf в incoming_dir/_failed/<run_id>/.

    Важно:
        Если .scanner.lock существует, cleanup по умолчанию пропускается.
    """

    if settings is None:
        settings = load_incoming_cleanup_settings_from_env()

    incoming_dir = Path(settings.incoming_dir)
    quarantine_dir = build_quarantine_run_dir(settings)
    lock_path = get_lock_path(settings)

    ensure_incoming_dir(settings)

    if settings.skip_if_lock_exists and lock_path.exists():
        logger.info(
            "Incoming cleanup skipped because scanner lock exists: lock_path=%s",
            lock_path,
        )

        return IncomingCleanupResult(
            action=action,
            incoming_dir=incoming_dir,
            quarantine_dir=quarantine_dir,
            skipped=True,
            skipped_reason=f"scanner lock exists: {lock_path}",
        )

    candidates = collect_stale_incoming_files(settings)

    logger.info(
        "Incoming cleanup candidates collected: action=%s incoming_dir=%s candidates=%s",
        action,
        incoming_dir,
        len(candidates),
    )

    if action == "dry_run":
        return IncomingCleanupResult(
            action=action,
            incoming_dir=incoming_dir,
            quarantine_dir=quarantine_dir,
            candidates=candidates,
        )

    if action != "quarantine":
        raise IncomingCleanupError(
            code="unknown_cleanup_action",
            operator_message="Некорректное действие очистки временной папки.",
            technical_message=f"Unknown action: {action!r}",
            path=incoming_dir,
        )

    ensure_quarantine_dir(quarantine_dir)

    quarantined_files: list[QuarantinedFile] = []
    file_errors: list[CleanupFileError] = []

    for candidate in candidates:
        try:
            quarantined = quarantine_file(
                candidate=candidate,
                quarantine_dir=quarantine_dir,
            )
            quarantined_files.append(quarantined)

            logger.info(
                "Incoming file quarantined: source_path=%s destination_path=%s size_bytes=%s",
                quarantined.source_path,
                quarantined.destination_path,
                quarantined.size_bytes,
            )

        except IncomingCleanupError as exc:
            file_errors.append(
                CleanupFileError(
                    path=candidate.path,
                    code=exc.code,
                    message=exc.technical_message or exc.operator_message,
                )
            )
            logger.warning("Incoming cleanup file error: %s", exc.to_log_dict())

    return IncomingCleanupResult(
        action=action,
        incoming_dir=incoming_dir,
        quarantine_dir=quarantine_dir,
        candidates=candidates,
        quarantined_files=quarantined_files,
        file_errors=file_errors,
    )
