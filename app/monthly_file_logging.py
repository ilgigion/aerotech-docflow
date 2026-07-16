from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
import os
import re
import threading


_HANDLER_MARKER = "_aerotech_docflow_monthly_file_handler"


class MonthlyTextFileHandler(logging.Handler):
    """
    Logging handler, который пишет обычные текстовые логи в файл текущего месяца.

    Пример имени файла:
        docflow_2026_07.txt

    При переходе месяца handler автоматически начнёт писать в новый файл.
    """

    def __init__(
        self,
        log_dir: Path | str,
        *,
        file_prefix: str = "docflow",
        encoding: str = "utf-8",
        level: int = logging.INFO,
        max_bytes: int = 0,
        backup_count: int = 5,
        retention_months: int = 0,
    ):
        super().__init__(level=level)
        self.log_dir = Path(log_dir)
        self.file_prefix = file_prefix
        self.encoding = encoding
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.retention_months = retention_months
        self._lock = threading.RLock()
        self._current_month: str | None = None
        self._stream = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with self._lock:
                self._ensure_stream(record)
                if self._stream is None:
                    return
                self._rotate_if_needed(len((message + "\n").encode(self.encoding)))
                self._stream.write(message + "\n")
                self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.flush()
                    self._stream.close()
                finally:
                    self._stream = None
        super().close()

    def _ensure_stream(self, record: logging.LogRecord) -> None:
        record_datetime = datetime.fromtimestamp(record.created)
        month_key = record_datetime.strftime("%Y_%m")

        if self._stream is not None and self._current_month == month_key:
            return

        if self._stream is not None:
            self._stream.flush()
            self._stream.close()
            self._stream = None

        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{self.file_prefix}_{month_key}.txt"
        self._stream = log_path.open("a", encoding=self.encoding)
        self._current_month = month_key
        self._prune_expired_months(record_datetime)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if self._stream is None or self.max_bytes <= 0:
            return
        try:
            current_size = self._stream.tell()
        except (OSError, ValueError):
            return
        if current_size + incoming_bytes <= self.max_bytes:
            return

        self._stream.flush()
        self._stream.close()
        self._stream = None
        base_path = self.log_dir / f"{self.file_prefix}_{self._current_month}.txt"
        if self.backup_count > 0:
            oldest = base_path.with_name(f"{base_path.name}.{self.backup_count}")
            oldest.unlink(missing_ok=True)
            for index in range(self.backup_count - 1, 0, -1):
                source = base_path.with_name(f"{base_path.name}.{index}")
                destination = base_path.with_name(f"{base_path.name}.{index + 1}")
                if source.exists():
                    os.replace(source, destination)
            if base_path.exists():
                os.replace(base_path, base_path.with_name(f"{base_path.name}.1"))
        else:
            base_path.unlink(missing_ok=True)
        self._stream = base_path.open("a", encoding=self.encoding)

    def _prune_expired_months(self, current: datetime) -> None:
        if self.retention_months <= 0:
            return
        current_index = current.year * 12 + current.month - 1
        minimum_index = current_index - self.retention_months + 1
        pattern = re.compile(
            rf"^{re.escape(self.file_prefix)}_(\d{{4}})_(\d{{2}})\.txt(?:\.\d+)?$"
        )
        for path in self.log_dir.iterdir():
            match = pattern.fullmatch(path.name)
            if not match or not path.is_file():
                continue
            year, month = int(match.group(1)), int(match.group(2))
            if month < 1 or month > 12:
                continue
            if year * 12 + month - 1 < minimum_index:
                try:
                    path.unlink()
                except OSError:
                    # Logging must not break the document flow because an old
                    # log file is temporarily locked by backup/antivirus.
                    pass


class _SafeExtraFormatter(logging.Formatter):
    """
    Обычный formatter, но оставлен отдельным классом, чтобы позже можно было
    централизованно дополнять формат operation_id/task_id без переписывания вызовов.
    """



def get_default_log_dir(incoming_dir: Path | str | None = None) -> Path:
    env_value = os.getenv("DOCFLOW_LOG_DIR", "").strip()
    if env_value:
        return Path(env_value)

    if incoming_dir is not None:
        return Path(incoming_dir) / "_logs"

    return Path(r"D:\incoming") / "_logs"



def monthly_log_file_path(log_dir: Path | str, *, at: datetime | None = None, file_prefix: str = "docflow") -> Path:
    if at is None:
        at = datetime.now()
    return Path(log_dir) / f"{file_prefix}_{at.strftime('%Y_%m')}.txt"



def configure_monthly_file_logging(
    *,
    log_dir: Path | str,
    level: int = logging.INFO,
    file_prefix: str = "docflow",
    max_bytes: int = 0,
    backup_count: int = 5,
    retention_months: int = 0,
) -> Path:
    """
    Подключает monthly txt logging к root logger.

    Функция идемпотентна: повторный вызов не создаёт дублирующиеся handlers,
    если handler с тем же log_dir/file_prefix уже подключён.

    Возвращает путь к файлу логов текущего месяца.
    """

    log_dir = Path(log_dir)
    root_logger = logging.getLogger()

    for handler in root_logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            if (
                Path(getattr(handler, "log_dir", "")) == log_dir
                and getattr(handler, "file_prefix", "") == file_prefix
            ):
                return monthly_log_file_path(log_dir, file_prefix=file_prefix)

    handler = MonthlyTextFileHandler(
        log_dir=log_dir,
        file_prefix=file_prefix,
        level=level,
        max_bytes=max_bytes,
        backup_count=backup_count,
        retention_months=retention_months,
    )
    setattr(handler, _HANDLER_MARKER, True)

    handler.setFormatter(
        _SafeExtraFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger.addHandler(handler)
    if root_logger.level > level:
        root_logger.setLevel(level)

    return monthly_log_file_path(log_dir, file_prefix=file_prefix)



def close_monthly_file_logging(
    *,
    log_dir: Path | str | None = None,
    file_prefix: str | None = None,
) -> int:
    """
    Отключает и закрывает monthly txt logging handlers.

    Нужна для тестов, перезапуска конфигурации и аккуратного завершения
    приложения на Windows, где открытый файл нельзя удалить/переместить.

    Если log_dir/file_prefix не переданы, закрываются все monthly handlers.
    Возвращает количество закрытых handlers.
    """

    root_logger = logging.getLogger()
    target_log_dir = Path(log_dir) if log_dir is not None else None
    closed_count = 0

    for handler in list(root_logger.handlers):
        if not getattr(handler, _HANDLER_MARKER, False):
            continue

        if target_log_dir is not None and Path(getattr(handler, "log_dir", "")) != target_log_dir:
            continue

        if file_prefix is not None and getattr(handler, "file_prefix", "") != file_prefix:
            continue

        root_logger.removeHandler(handler)
        handler.close()
        closed_count += 1

    return closed_count


def configure_monthly_file_logging_from_env(incoming_dir: Path | str | None = None) -> Path | None:
    """
    Включает месячные txt-логи, если DOCFLOW_MONTHLY_FILE_LOGS не равен 0.

    Переменные окружения:
        DOCFLOW_MONTHLY_FILE_LOGS=0     отключить
        DOCFLOW_LOG_DIR=D:\\incoming\\_logs
        DOCFLOW_LOG_LEVEL=INFO
    """

    enabled = os.getenv("DOCFLOW_MONTHLY_FILE_LOGS", "1").strip() != "0"
    if not enabled:
        return None

    level_name = os.getenv("DOCFLOW_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)

    return configure_monthly_file_logging(
        log_dir=get_default_log_dir(incoming_dir),
        level=level,
        max_bytes=int(os.getenv("DOCFLOW_LOG_MAX_BYTES", "0")),
        backup_count=int(os.getenv("DOCFLOW_LOG_BACKUP_COUNT", "5")),
        retention_months=int(os.getenv("DOCFLOW_LOG_RETENTION_MONTHS", "0")),
    )
