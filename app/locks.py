from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import logging
import os
import secrets
import socket
import time


logger = logging.getLogger(__name__)


class ScannerLockError(RuntimeError):
    """
    Базовая ошибка блокировки сканера.

    operator_message — короткое понятное сообщение для оператора.
    technical_message — подробности для логов/администратора.
    """

    def __init__(
        self,
        code: str,
        operator_message: str,
        technical_message: str = "",
        lock_path: Path | None = None,
        lock_info: dict[str, Any] | None = None,
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.lock_path = lock_path
        self.lock_info = lock_info or {}

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "lock_path": str(self.lock_path) if self.lock_path else None,
            "lock_info": self.lock_info,
        }


class ScannerLockBusyError(ScannerLockError):
    pass


class ScannerLockCreateError(ScannerLockError):
    pass


class ScannerLockReleaseError(ScannerLockError):
    pass


class ScannerLockInvalidError(ScannerLockError):
    pass


@dataclass(frozen=True)
class ScannerLockSettings:
    """
    Настройки file lock.

    lock_file:
        Если None, document_flow.py использует:
            scanner_settings.incoming_dir / ".scanner.lock"

    stale_after_seconds:
        Через сколько секунд lock можно считать старым.
        По умолчанию 30 минут.

    wait_timeout_seconds:
        Сколько ждать освобождения lock.
        0 означает: не ждать, сразу вернуть "сканер занят".

    retry_interval_seconds:
        Пауза между попытками захвата lock.

    allow_stale_takeover:
        Если True, старый lock можно заменить.
    """

    lock_file: Path | None = None
    stale_after_seconds: int = 30 * 60
    wait_timeout_seconds: float = 0
    retry_interval_seconds: float = 0.5
    allow_stale_takeover: bool = True


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_lock_settings_from_env() -> ScannerLockSettings:
    return ScannerLockSettings(
        stale_after_seconds=int(os.getenv("SCANNER_LOCK_STALE_SECONDS", "1800")),
        wait_timeout_seconds=float(
            os.getenv("SCANNER_LOCK_WAIT_TIMEOUT_SECONDS", "0")
        ),
        retry_interval_seconds=float(
            os.getenv("SCANNER_LOCK_RETRY_INTERVAL_SECONDS", "0.5")
        ),
        allow_stale_takeover=_env_flag("SCANNER_LOCK_ALLOW_STALE_TAKEOVER", True),
    )


@dataclass(frozen=True)
class LockInfo:
    operation_id: str
    task_id: str
    pid: int
    hostname: str
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "pid": self.pid,
            "hostname": self.hostname,
            "created_at_utc": self.created_at_utc,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_datetime_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def read_lock_info(lock_path: Path) -> dict[str, Any] | None:
    """
    Читает lock-файл.

    Возвращает:
        dict — если файл есть и JSON прочитан;
        None — если файла нет.

    Если файл есть, но повреждён, возвращаем технический dict,
    чтобы администратор видел проблему.
    """

    if not lock_path.exists():
        return None

    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {
                "invalid_lock_file": True,
                "raw_text": lock_path.read_text(encoding="utf-8", errors="replace"),
            }
        return data

    except json.JSONDecodeError:
        return {
            "invalid_lock_file": True,
            "raw_text": lock_path.read_text(encoding="utf-8", errors="replace"),
        }

    except OSError as exc:
        return {
            "unreadable_lock_file": True,
            "error": str(exc),
        }


def is_process_running(pid: int | None) -> bool:
    """
    Проверяет, жив ли процесс на текущей машине.

    На Windows os.kill(pid, 0) не убивает процесс, а проверяет его существование.
    Если нет прав на процесс, считаем, что он существует.
    """

    if not pid or pid <= 0:
        return False

    try:
        os.kill(pid, 0)

    except ProcessLookupError:
        return False

    except PermissionError:
        return True

    except OSError:
        return False

    return True


def is_lock_stale(
    lock_info: dict[str, Any] | None,
    stale_after_seconds: int,
) -> bool:
    """
    Определяет, можно ли считать lock зависшим.

    Логика:
    - если lock не читается как нормальный JSON — fail-closed, только ручное восстановление;
    - если нет created_at_utc — fail-closed, только ручное восстановление;
    - если lock моложе stale_after_seconds — не stale;
    - если lock старый и процесс на этой же машине ещё жив — не stale;
    - иначе stale.
    """

    if not lock_info:
        return False

    if lock_info.get("invalid_lock_file") or lock_info.get("unreadable_lock_file"):
        return False

    created_at_raw = str(lock_info.get("created_at_utc", ""))
    created_at = parse_datetime_utc(created_at_raw)

    if created_at is None:
        return False

    age_seconds = (utc_now() - created_at).total_seconds()

    if age_seconds < stale_after_seconds:
        return False

    current_hostname = socket.gethostname()
    lock_hostname = str(lock_info.get("hostname", ""))
    lock_pid = lock_info.get("pid")

    try:
        lock_pid_int = int(lock_pid)
    except (TypeError, ValueError):
        lock_pid_int = None

    # Если lock создан на этой же машине и процесс ещё жив,
    # автоматически не забираем lock, даже если он старый.
    # Иначе можно прервать реальную долгую операцию.
    if lock_hostname == current_hostname and is_process_running(lock_pid_int):
        return False

    return True


def build_lock_info(operation_id: str, task_id: str) -> LockInfo:
    return LockInfo(
        operation_id=str(operation_id),
        task_id=str(task_id),
        pid=os.getpid(),
        hostname=socket.gethostname(),
        created_at_utc=utc_now_iso(),
    )


def _write_lock_file_atomically(lock_path: Path, lock_info: LockInfo) -> None:
    """
    Атомарно создаёт lock-файл.

    os.O_CREAT | os.O_EXCL означает:
        создать файл только если его ещё нет.

    Это защищает от гонки:
        два процесса одновременно проверили, что lock нет,
        и оба решили начать сканирование.
    """

    temp_path = lock_path.with_name(
        f".{lock_path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    try:
        with temp_path.open("x", encoding="utf-8") as file:
            json.dump(
                lock_info.to_dict(),
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.link(str(temp_path), str(lock_path))
    except FileExistsError:
        raise
    except OSError as exc:
        raise ScannerLockCreateError(
            code="scanner_lock_create_error",
            operator_message="Не удалось атомарно создать блокировку сканера.",
            technical_message=str(exc),
            lock_path=lock_path,
        ) from exc
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


class ScannerFileLock(AbstractContextManager["ScannerFileLock"]):
    """
    Контекстный менеджер file lock.

    Использование:

        with ScannerFileLock(...):
            scan_document()
            store_document()

    Lock освобождается в __exit__, то есть срабатывает даже при исключении.
    """

    def __init__(
        self,
        lock_path: Path,
        operation_id: str,
        task_id: str,
        stale_after_seconds: int = 30 * 60,
        wait_timeout_seconds: float = 0,
        retry_interval_seconds: float = 0.5,
        allow_stale_takeover: bool = True,
    ):
        self.lock_path = Path(lock_path)
        self.operation_id = str(operation_id)
        self.task_id = str(task_id)
        self.stale_after_seconds = int(stale_after_seconds)
        self.wait_timeout_seconds = float(wait_timeout_seconds)
        self.retry_interval_seconds = float(retry_interval_seconds)
        self.allow_stale_takeover = bool(allow_stale_takeover)

        self._owns_lock = False
        self._lock_info = build_lock_info(
            operation_id=self.operation_id,
            task_id=self.task_id,
        )

    def __enter__(self) -> "ScannerFileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if getattr(exc_value, "preserve_scanner_lock", False):
            logger.critical(
                "Scanner lock intentionally preserved for manual recovery: "
                "lock_path=%s operation_id=%s task_id=%s error=%s",
                self.lock_path,
                self.operation_id,
                self.task_id,
                exc_value,
            )
            self._owns_lock = False
            return
        self.release()

    @property
    def lock_info(self) -> dict[str, Any]:
        return self._lock_info.to_dict()

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        deadline = time.monotonic() + self.wait_timeout_seconds

        while True:
            try:
                _write_lock_file_atomically(
                    lock_path=self.lock_path,
                    lock_info=self._lock_info,
                )

                self._owns_lock = True
                logger.info(
                    "Scanner lock acquired: lock_path=%s operation_id=%s task_id=%s",
                    self.lock_path,
                    self.operation_id,
                    self.task_id,
                )
                return

            except FileExistsError:
                existing_lock_info = read_lock_info(self.lock_path)

                if (
                    self.allow_stale_takeover
                    and is_lock_stale(
                        lock_info=existing_lock_info,
                        stale_after_seconds=self.stale_after_seconds,
                    )
                ):
                    logger.warning(
                        "Removing stale scanner lock: lock_path=%s lock_info=%s",
                        self.lock_path,
                        existing_lock_info,
                    )

                    try:
                        self.lock_path.unlink(missing_ok=True)

                    except OSError as exc:
                        raise ScannerLockBusyError(
                            code="scanner_lock_stale_remove_error",
                            operator_message="Сканер заблокирован предыдущей операцией. Не удалось снять старую блокировку.",
                            technical_message=str(exc),
                            lock_path=self.lock_path,
                            lock_info=existing_lock_info,
                        ) from exc

                    # После удаления старого lock сразу пробуем снова.
                    continue

                if self.wait_timeout_seconds > 0 and time.monotonic() < deadline:
                    time.sleep(self.retry_interval_seconds)
                    continue

                raise ScannerLockBusyError(
                    code="scanner_locked",
                    operator_message="Сканер уже используется. Дождитесь завершения текущего сканирования и повторите попытку.",
                    technical_message="Scanner lock file already exists",
                    lock_path=self.lock_path,
                    lock_info=existing_lock_info,
                )

    def release(self) -> None:
        if not self._owns_lock:
            return

        existing_lock_info = read_lock_info(self.lock_path)

        # Не удаляем lock, если он уже принадлежит другой операции.
        # Такое может случиться после ручного удаления/создания или stale takeover.
        if not self._is_our_lock(existing_lock_info):
            logger.warning(
                "Scanner lock was not released because it belongs to another operation: "
                "lock_path=%s expected=%s actual=%s",
                self.lock_path,
                self.lock_info,
                existing_lock_info,
            )
            self._owns_lock = False
            return

        try:
            self.lock_path.unlink(missing_ok=True)
            logger.info(
                "Scanner lock released: lock_path=%s operation_id=%s task_id=%s",
                self.lock_path,
                self.operation_id,
                self.task_id,
            )

        except OSError as exc:
            raise ScannerLockReleaseError(
                code="scanner_lock_release_error",
                operator_message="Не удалось освободить блокировку сканера.",
                technical_message=str(exc),
                lock_path=self.lock_path,
                lock_info=self.lock_info,
            ) from exc

        finally:
            self._owns_lock = False

    def _is_our_lock(self, lock_info: dict[str, Any] | None) -> bool:
        if not lock_info:
            return False

        return (
            lock_info.get("operation_id") == self.operation_id
            and str(lock_info.get("task_id")) == self.task_id
            and int(lock_info.get("pid", -1)) == os.getpid()
            and lock_info.get("hostname") == socket.gethostname()
        )


def scanner_lock(
    lock_path: Path,
    operation_id: str,
    task_id: str,
    settings: ScannerLockSettings | None = None,
) -> ScannerFileLock:
    """
    Фабрика для короткого использования:

        with scanner_lock(lock_path, operation_id, task_id):
            ...
    """

    if settings is None:
        settings = ScannerLockSettings()

    return ScannerFileLock(
        lock_path=lock_path,
        operation_id=operation_id,
        task_id=str(task_id),
        stale_after_seconds=settings.stale_after_seconds,
        wait_timeout_seconds=settings.wait_timeout_seconds,
        retry_interval_seconds=settings.retry_interval_seconds,
        allow_stale_takeover=settings.allow_stale_takeover,
    )


def force_remove_lock(lock_path: Path) -> bool:
    """
    Ручное удаление lock-файла.

    Использовать только в админских сценариях:
    - убедиться, что нет активного сканирования;
    - убедиться, что нет процесса python/NAPS2;
    - затем удалить lock.

    Возвращает True, если файл был удалён.
    """

    lock_path = Path(lock_path)

    if not lock_path.exists():
        return False

    lock_path.unlink()
    return True
