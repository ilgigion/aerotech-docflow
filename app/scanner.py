from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
import locale
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
import unicodedata


logger = logging.getLogger(__name__)
MAX_SCANNER_PROFILE_LENGTH = 200


def validate_scanner_profile_name(value: str) -> str:
    """Return a safe, exact NAPS2 profile name."""

    if not isinstance(value, str):
        raise ValueError("scanner_profile must be a string")
    profile_name = value.strip()
    if not profile_name:
        raise ValueError("scanner_profile must not be blank")
    if len(profile_name) > MAX_SCANNER_PROFILE_LENGTH:
        raise ValueError(
            f"scanner_profile must contain at most {MAX_SCANNER_PROFILE_LENGTH} characters"
        )
    if any(unicodedata.category(character).startswith("C") for character in profile_name):
        raise ValueError("scanner_profile contains control or formatting characters")
    return profile_name


@dataclass(frozen=True)
class EnvironmentCheck:
    name: str
    ok: bool
    message: str
    details: str = ""


class ScannerError(RuntimeError):
    """
    Базовая ошибка сканера.

    operator_message — понятное сообщение для оператора.
    technical_message — подробности для логов/администратора.
    """

    def __init__(
        self,
        code: str,
        operator_message: str,
        technical_message: str = "",
        output_path: Path | None = None,
        stdout: str = "",
        stderr: str = "",
        return_code: int | None = None,
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.output_path = output_path
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "output_path": str(self.output_path) if self.output_path else None,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
        }


class ScannerExecutableNotFoundError(ScannerError):
    pass


class ScannerIncomingDirectoryError(ScannerError):
    pass


class ScannerInvalidTaskIdError(ScannerError):
    pass


class ScannerInvalidSettingsError(ScannerError):
    pass


class ScannerTimeoutError(ScannerError):
    pass


class ScannerInterruptedError(ScannerError):
    pass


class ScannerBusyError(ScannerError):
    pass


class ScannerConnectionError(ScannerError):
    pass


class ScannerNoPagesError(ScannerError):
    pass


class ScannerProcessError(ScannerError):
    pass


class ScannerProcessStillRunningError(ScannerProcessError):
    """NAPS2 остался жив после принудительного завершения."""

    preserve_scanner_lock = True


class ScannerOutputMissingError(ScannerError):
    pass


class ScannerOutputInvalidError(ScannerError):
    pass


@dataclass(frozen=True)
class ScannerSettings:
    """
    Настройки сканера.

    Если profile_name указан, используется команда:
        NAPS2.Console.exe -o output.pdf -p ProfileName

    Если profile_name=None, используется команда:
        NAPS2.Console.exe -o output.pdf --noprofile --driver ... --device ...
    """

    naps2_executable: Path | None = None
    incoming_dir: Path | None = None

    profile_name: str | None = None

    driver: str = ""
    device_name: str = ""
    source: str | None = None
    dpi: int | None = None
    page_size: str | None = None
    bit_depth: str | None = None

    # Таймаут внешнего процесса NAPS2.
    # Для рабочего Epson обычно хватает 180 секунд с большим запасом.
    timeout_seconds: int = 180

    # Сколько ждать stdout/stderr после принудительного завершения NAPS2.
    timeout_kill_grace_seconds: int = 10

    # Сколько секунд проверять, что процесс действительно завершился после taskkill/kill.
    verify_process_exit_seconds: int = 5

    # Если NAPS2 упал/завис/был прерван и успел создать временный PDF,
    # переносим этот недоверенный файл в карантин, а не оставляем в incoming.
    quarantine_failed_scan_outputs: bool = True
    failed_scan_dir_name: str = "_failed_runtime"

    min_pdf_size_bytes: int = 100

    stable_checks: int = 2
    stable_interval_seconds: float = 0.5

    # NAPS2 на Windows часто пишет stdout в OEM-кодировке cp866.
    # Если оставить системную cp1251, русский текст превращается в "кракозябры".
    naps2_output_encoding: str | None = None

    # Строгую проверку количества страниц делаем только если будет подключена
    # внешняя PDF-библиотека. Сейчас поле оставлено для будущего расширения.
    min_pdf_pages: int = 1


def load_settings_from_env() -> ScannerSettings:
    naps2_executable = os.getenv("NAPS2_EXECUTABLE", "").strip()
    incoming_dir = os.getenv("SCANNER_INCOMING_DIR", "").strip()
    if not naps2_executable:
        raise ScannerInvalidSettingsError(
            code="missing_naps2_executable",
            operator_message="Не настроен путь к NAPS2. Обратитесь к администратору.",
            technical_message="NAPS2_EXECUTABLE is empty; set scanner.naps2_executable in config.toml",
        )
    if not incoming_dir:
        raise ScannerInvalidSettingsError(
            code="missing_scanner_incoming_dir",
            operator_message="Не настроена временная папка сканирования. Обратитесь к администратору.",
            technical_message="SCANNER_INCOMING_DIR is empty; set scanner.incoming_dir in config.toml",
        )
    profile_name = os.getenv("NAPS2_PROFILE", "").strip()
    if profile_name == "":
        profile_name = None

    source = os.getenv("SCANNER_SOURCE", "").strip()
    if source == "":
        source = None

    dpi_value = os.getenv("SCANNER_DPI", "").strip()
    page_size = os.getenv("SCANNER_PAGE_SIZE", "").strip() or None
    bit_depth = os.getenv("SCANNER_BIT_DEPTH", "").strip() or None

    return ScannerSettings(
        naps2_executable=Path(naps2_executable),
        incoming_dir=Path(incoming_dir),
        profile_name=profile_name,
        driver=os.getenv("SCANNER_DRIVER", "").strip(),
        device_name=os.getenv("SCANNER_DEVICE_NAME", "").strip(),
        source=source,
        dpi=int(dpi_value) if dpi_value else None,
        page_size=page_size,
        bit_depth=bit_depth,
        timeout_seconds=int(os.getenv("SCANNER_TIMEOUT_SECONDS", "180")),
        timeout_kill_grace_seconds=int(os.getenv("SCANNER_TIMEOUT_KILL_GRACE_SECONDS", "10")),
        verify_process_exit_seconds=int(os.getenv("SCANNER_VERIFY_PROCESS_EXIT_SECONDS", "5")),
        quarantine_failed_scan_outputs=os.getenv("SCANNER_QUARANTINE_FAILED_OUTPUTS", "1").strip() != "0",
        failed_scan_dir_name=os.getenv("SCANNER_FAILED_SCAN_DIR_NAME", "_failed_runtime"),
        min_pdf_size_bytes=int(os.getenv("SCANNER_MIN_PDF_SIZE_BYTES", "100")),
        stable_checks=int(os.getenv("SCANNER_STABLE_CHECKS", "2")),
        stable_interval_seconds=float(os.getenv("SCANNER_STABLE_INTERVAL_SECONDS", "0.5")),
        naps2_output_encoding=os.getenv("NAPS2_OUTPUT_ENCODING", "").strip() or None,
        min_pdf_pages=int(os.getenv("SCANNER_MIN_PDF_PAGES", "1")),
    )


def validate_scanner_settings(settings: ScannerSettings) -> None:
    if settings.naps2_executable is None:
        raise ScannerInvalidSettingsError(
            code="missing_naps2_executable",
            operator_message="Не настроен путь к NAPS2. Обратитесь к администратору.",
            technical_message="ScannerSettings.naps2_executable is None",
        )
    if settings.incoming_dir is None:
        raise ScannerInvalidSettingsError(
            code="missing_scanner_incoming_dir",
            operator_message="Не настроена временная папка сканирования. Обратитесь к администратору.",
            technical_message="ScannerSettings.incoming_dir is None",
        )
    if settings.timeout_seconds <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_scanner_timeout",
            operator_message="Некорректный таймаут сканирования. Обратитесь к администратору.",
            technical_message=f"timeout_seconds={settings.timeout_seconds}",
        )

    if settings.timeout_kill_grace_seconds <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_timeout_kill_grace",
            operator_message="Некорректная настройка завершения зависшего сканирования. Обратитесь к администратору.",
            technical_message=f"timeout_kill_grace_seconds={settings.timeout_kill_grace_seconds}",
        )

    if settings.verify_process_exit_seconds <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_process_exit_verify",
            operator_message="Некорректная настройка проверки завершения процесса сканирования. Обратитесь к администратору.",
            technical_message=f"verify_process_exit_seconds={settings.verify_process_exit_seconds}",
        )

    if not settings.failed_scan_dir_name or any(ch in settings.failed_scan_dir_name for ch in "<>:\"/|?*"):
        raise ScannerInvalidSettingsError(
            code="invalid_failed_scan_dir_name",
            operator_message="Некорректная настройка папки аварийных сканов. Обратитесь к администратору.",
            technical_message=f"failed_scan_dir_name={settings.failed_scan_dir_name!r}",
        )

    if settings.min_pdf_size_bytes <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_min_pdf_size",
            operator_message="Некорректная настройка минимального размера PDF. Обратитесь к администратору.",
            technical_message=f"min_pdf_size_bytes={settings.min_pdf_size_bytes}",
        )

    if settings.stable_checks <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_stable_checks",
            operator_message="Некорректная настройка проверки файла. Обратитесь к администратору.",
            technical_message=f"stable_checks={settings.stable_checks}",
        )

    if settings.stable_interval_seconds <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_stable_interval",
            operator_message="Некорректная настройка проверки файла. Обратитесь к администратору.",
            technical_message=f"stable_interval_seconds={settings.stable_interval_seconds}",
        )

    if settings.min_pdf_pages <= 0:
        raise ScannerInvalidSettingsError(
            code="invalid_min_pdf_pages",
            operator_message="Некорректная настройка минимального количества страниц PDF. Обратитесь к администратору.",
            technical_message=f"min_pdf_pages={settings.min_pdf_pages}",
        )

    if settings.profile_name:
        return

    if not settings.driver or not str(settings.driver).strip():
        raise ScannerInvalidSettingsError(
            code="empty_scanner_driver",
            operator_message="Не указан драйвер сканера. Обратитесь к администратору.",
            technical_message="driver is empty and profile_name is not set",
        )

    if not settings.device_name or not str(settings.device_name).strip():
        raise ScannerInvalidSettingsError(
            code="empty_scanner_device",
            operator_message="Не указано имя сканера. Обратитесь к администратору.",
            technical_message="device_name is empty and profile_name is not set",
        )


def prepare_environment(settings: ScannerSettings) -> None:
    """
    Проверяем, что NAPS2 существует и что во временную папку можно писать.
    """

    validate_scanner_settings(settings)

    if not Path(settings.naps2_executable).is_file():
        raise ScannerExecutableNotFoundError(
            code="naps2_not_found",
            operator_message="Не найден NAPS2.Console.exe. Обратитесь к администратору.",
            technical_message=f"File not found: {settings.naps2_executable}",
        )

    incoming_dir = Path(settings.incoming_dir)

    try:
        if incoming_dir.exists() and not incoming_dir.is_dir():
            raise OSError(f"Incoming path exists but is not a directory: {incoming_dir}")

        incoming_dir.mkdir(parents=True, exist_ok=True)

        test_file = incoming_dir / ".scanner_write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)

    except OSError as exc:
        raise ScannerIncomingDirectoryError(
            code="incoming_dir_error",
            operator_message="Нет доступа к папке временных сканов. Обратитесь к администратору.",
            technical_message=str(exc),
        ) from exc


def check_scanner_environment(settings: ScannerSettings) -> list[EnvironmentCheck]:
    """
    Диагностика окружения сканера без запуска сканирования.
    """

    checks: list[EnvironmentCheck] = []

    try:
        validate_scanner_settings(settings)
        checks.append(EnvironmentCheck("settings", True, "Настройки сканера корректны"))
    except ScannerError as exc:
        checks.append(EnvironmentCheck("settings", False, exc.operator_message, exc.technical_message))

    naps2_path = Path(settings.naps2_executable)
    checks.append(
        EnvironmentCheck(
            "naps2_executable",
            naps2_path.is_file(),
            "NAPS2.Console.exe найден" if naps2_path.is_file() else "NAPS2.Console.exe не найден",
            str(naps2_path),
        )
    )

    incoming_dir = Path(settings.incoming_dir)
    try:
        if incoming_dir.exists() and not incoming_dir.is_dir():
            raise OSError(f"Path exists but is not a directory: {incoming_dir}")

        incoming_dir.mkdir(parents=True, exist_ok=True)
        test_file = incoming_dir / ".scanner_write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        checks.append(EnvironmentCheck("incoming_dir", True, "Временная папка доступна на запись", str(incoming_dir)))

    except OSError as exc:
        checks.append(EnvironmentCheck("incoming_dir", False, "Временная папка недоступна на запись", str(exc)))

    return checks


def build_output_path(task_id: int | str, incoming_dir: Path) -> Path:
    raw_task_id = str(task_id).strip()

    if not raw_task_id:
        raise ScannerInvalidTaskIdError(
            code="invalid_task_id",
            operator_message="Не передан номер задачи для сканирования.",
            technical_message="task_id is empty",
        )

    safe_task_id = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_task_id).strip("_")

    if not safe_task_id:
        raise ScannerInvalidTaskIdError(
            code="invalid_task_id",
            operator_message="Некорректный номер задачи для сканирования.",
            technical_message=f"task_id={task_id!r}",
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)

    return Path(incoming_dir) / f"PF_{safe_task_id}_{timestamp}_{suffix}.pdf"


def build_naps2_command(settings: ScannerSettings, output_path: Path) -> list[str]:
    command = [
        str(settings.naps2_executable),
        "-o",
        str(output_path),
    ]

    if settings.profile_name:
        command.extend(["-p", settings.profile_name])
        return command

    command.extend(
        [
            "--noprofile",
            "--driver",
            settings.driver,
            "--device",
            settings.device_name,
        ]
    )

    if settings.source:
        command.extend(["--source", settings.source])

    if settings.dpi:
        command.extend(["--dpi", str(settings.dpi)])

    if settings.page_size:
        command.extend(["--pagesize", settings.page_size])

    if settings.bit_depth:
        command.extend(["--bitdepth", settings.bit_depth])

    return command


def _get_console_encoding() -> str:
    return locale.getpreferredencoding(False) or "utf-8"


def _get_naps2_output_encoding(settings: ScannerSettings | None = None) -> str:
    """
    Кодировка stdout/stderr NAPS2.

    На русской Windows NAPS2.Console часто пишет текст в OEM-кодировке cp866,
    а Python по умолчанию может читать через cp1251. Из-за этого сообщение
    "В податчике нет листов" превращается в "‚ Ї®¤...".
    """

    if settings and settings.naps2_output_encoding:
        return settings.naps2_output_encoding

    env_encoding = os.getenv("NAPS2_OUTPUT_ENCODING", "").strip()
    if env_encoding:
        return env_encoding

    if os.name == "nt":
        return "cp866"

    return _get_console_encoding()


def _to_text(value: str | bytes | None, encoding: str | None = None) -> str:
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode(encoding or _get_console_encoding(), errors="replace")

    return str(value)


def classify_naps2_error(
    stdout: str,
    stderr: str,
    output_path: Path,
    return_code: int | None,
) -> ScannerError | None:
    combined = f"{stdout}\n{stderr}".lower()

    connection_markers = (
        "the ssl connection could not be established",
        "the server returned an invalid or unrecognized response",
        "selected scanner is disconnected",
        "selected scanner is offline",
        "выбранный сканер отключён",
        "выбранный сканер отключен",
        "network is unreachable",
        "connection refused",
    )
    matched_connection_marker = next(
        (marker for marker in connection_markers if marker in combined),
        None,
    )
    if matched_connection_marker is not None:
        return ScannerConnectionError(
            code="scanner_connection_error",
            operator_message=(
                "Сканер недоступен по сети. Проверьте VPN, сетевое подключение "
                "и состояние сканера, затем повторите попытку."
            ),
            technical_message=f"NAPS2 connection marker: {matched_connection_marker}",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

    if "no scanned pages" in combined:
        return ScannerNoPagesError(
            code="no_scanned_pages",
            operator_message="Сканирование завершилось, но страницы не были получены. Проверьте, что документ установлен в сканер.",
            technical_message="NAPS2 returned: No scanned pages to export.",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

    if "5,157,69" in combined or "157,69" in combined:
        return ScannerConnectionError(
            code="scanner_connection_error",
            operator_message="Сканер недоступен по сети или соединение заблокировано. Проверьте VPN, сеть, firewall и повторите попытку.",
            technical_message="Canon ScanGear connection error: 5,157,69",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

    if "255,0,0" in combined:
        return ScannerProcessError(
            code="scanner_driver_error",
            operator_message="Сканер вернул ошибку драйвера. Проверьте устройство и повторите попытку.",
            technical_message="Canon ScanGear driver error: 255,0,0",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

    if "device not found" in combined or "scanner not found" in combined or "устройство не найден" in combined:
        return ScannerConnectionError(
            code="scanner_not_found",
            operator_message="Сканер не найден. Проверьте имя устройства, подключение и сеть.",
            technical_message="NAPS2/driver reported scanner not found",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

    if (
        "busy" in combined
        or "занят" in combined
        or "заблокирована другим процессом" in combined
        or "blocked by another process" in combined
    ):
        return ScannerBusyError(
            code="scanner_busy",
            operator_message="Сканер занят или заблокирован другой программой. Закройте программы сканирования и повторите попытку.",
            technical_message="Scanner busy or locked",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

    return None


def kill_process_tree(process: subprocess.Popen, operation_id: str | None = None) -> None:
    """
    Принудительно завершает процесс NAPS2 и его дочерние процессы.

    Windows:
        taskkill /PID <pid> /T /F

    Другие ОС:
        process.kill()

    Важно:
        убиваем только процесс, который запустили сами, по его PID.
    """

    if process.poll() is not None:
        return

    logger.warning(
        "Killing NAPS2 process tree operation_id=%s pid=%s",
        operation_id,
        process.pid,
    )

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            logger.warning(
                "taskkill finished operation_id=%s pid=%s return_code=%s stdout=%r stderr=%r",
                operation_id,
                process.pid,
                result.returncode,
                result.stdout,
                result.stderr,
            )
            if result.returncode == 0 and process.poll() is not None:
                return

            logger.error(
                "taskkill did not stop NAPS2; using process.kill fallback "
                "operation_id=%s pid=%s return_code=%s process_alive=%s",
                operation_id,
                process.pid,
                result.returncode,
                process.poll() is None,
            )

        except Exception as exc:
            logger.exception(
                "Failed to kill NAPS2 process tree through taskkill operation_id=%s pid=%s error=%s",
                operation_id,
                process.pid,
                exc,
            )

    try:
        process.kill()

    except Exception as exc:
        logger.exception(
            "Failed to kill NAPS2 process operation_id=%s pid=%s error=%s",
            operation_id,
            process.pid,
            exc,
        )


def _collect_output_after_kill(
    process: subprocess.Popen,
    *,
    timeout_seconds: int,
    stdout_fallback: str = "",
    stderr_fallback: str = "",
) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return stdout or "", stderr or ""

    except subprocess.TimeoutExpired:
        return stdout_fallback or "", stderr_fallback or ""


def verify_process_stopped(
    process: subprocess.Popen,
    *,
    operation_id: str | None = None,
    max_wait_seconds: int = 5,
) -> bool:
    """
    Проверяет, что запущенный нами NAPS2-процесс действительно завершился.

    Это важно после timeout/прерывания: сервер должен понимать, остался ли
    внешний процесс жить и может ли он держать сессию сканера.
    """

    deadline = time.monotonic() + max_wait_seconds

    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            logger.info(
                "NAPS2 process stopped operation_id=%s pid=%s return_code=%s",
                operation_id,
                process.pid,
                return_code,
            )
            return True

        time.sleep(0.2)

    logger.error(
        "NAPS2 process still alive after forced termination operation_id=%s pid=%s manual_check_required=1",
        operation_id,
        process.pid,
    )
    return False


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}_{timestamp}{path.suffix}")


def quarantine_untrusted_output(
    output_path: Path,
    *,
    reason: str,
    settings: ScannerSettings,
    operation_id: str | None = None,
) -> Path | None:
    """
    Переносит недоверенный временный результат сканирования в карантин.

    Используется только для аварийных случаев: timeout, KeyboardInterrupt,
    return_code != 0, невалидный PDF. Успешный PDF при ошибке storage не
    трогаем — он остаётся в incoming для retry_store_existing_scan().
    """

    if not settings.quarantine_failed_scan_outputs:
        logger.info(
            "Untrusted scan output quarantine disabled operation_id=%s path=%s reason=%s",
            operation_id,
            output_path,
            reason,
        )
        return None

    output_path = Path(output_path)

    if not output_path.exists():
        return None

    if not output_path.is_file():
        logger.warning(
            "Untrusted scan output is not a file operation_id=%s path=%s reason=%s",
            operation_id,
            output_path,
            reason,
        )
        return None

    safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", reason).strip("_") or "scan_failure"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine_dir = output_path.parent / settings.failed_scan_dir_name / f"{timestamp}_{safe_reason}"

    try:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        destination_path = _unique_path(quarantine_dir / output_path.name)
        shutil.move(str(output_path), str(destination_path))

        logger.warning(
            "Untrusted scan output quarantined operation_id=%s reason=%s source_path=%s quarantine_path=%s",
            operation_id,
            reason,
            output_path,
            destination_path,
        )
        return destination_path

    except OSError as exc:
        logger.exception(
            "Failed to quarantine untrusted scan output operation_id=%s reason=%s path=%s error=%s",
            operation_id,
            reason,
            output_path,
            exc,
        )
        return None


def _append_quarantine_info(error: ScannerError, quarantine_path: Path | None) -> None:
    if quarantine_path is None:
        return

    suffix = f"; quarantined_untrusted_output={quarantine_path}"
    if suffix not in error.technical_message:
        error.technical_message = f"{error.technical_message}{suffix}" if error.technical_message else suffix.lstrip("; ")


def run_naps2(
    command: list[str],
    settings: ScannerSettings,
    output_path: Path,
    operation_id: str | None = None,
) -> None:
    """
    Запускаем NAPS2 и ждём завершения.

    Защиты:
    - timeout завершает именно запущенный нами NAPS2-процесс;
    - Ctrl+C / KeyboardInterrupt тоже завершает NAPS2;
    - lock освобождается выше в document_flow.py через context manager.
    """

    start_time = time.monotonic()
    output_encoding = _get_naps2_output_encoding(settings)

    logger.info(
        "Starting NAPS2 scan operation_id=%s output_path=%s command=%s output_encoding=%s",
        operation_id,
        output_path,
        command,
        output_encoding,
    )

    process: subprocess.Popen | None = None
    stdout = ""
    stderr = ""

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=output_encoding,
            errors="replace",
        )

        try:
            stdout, stderr = process.communicate(timeout=settings.timeout_seconds)

        except subprocess.TimeoutExpired as exc:
            duration_seconds = round(time.monotonic() - start_time, 3)

            logger.error(
                "NAPS2 timeout operation_id=%s duration_seconds=%s output_path=%s pid=%s",
                operation_id,
                duration_seconds,
                output_path,
                process.pid,
            )

            kill_process_tree(process=process, operation_id=operation_id)
            process_stopped = verify_process_stopped(
                process,
                operation_id=operation_id,
                max_wait_seconds=settings.verify_process_exit_seconds,
            )

            stdout, stderr = _collect_output_after_kill(
                process,
                timeout_seconds=settings.timeout_kill_grace_seconds,
                stdout_fallback=_to_text(exc.stdout, output_encoding),
                stderr_fallback=_to_text(exc.stderr, output_encoding),
            )

            quarantine_path = quarantine_untrusted_output(
                output_path,
                reason="scanner_timeout",
                settings=settings,
                operation_id=operation_id,
            )

            if not process_stopped:
                raise ScannerProcessStillRunningError(
                    code="scanner_process_still_running",
                    operator_message=(
                        "NAPS2 не удалось остановить после тайм-аута. "
                        "Блокировка сканера сохранена; требуется ручная диагностика."
                    ),
                    technical_message=(
                        f"NAPS2 still alive after timeout; pid={process.pid}; "
                        f"quarantine_path={quarantine_path}; manual_recovery_required=1"
                    ),
                    output_path=output_path,
                    stdout=stdout,
                    stderr=stderr,
                ) from exc

            raise ScannerTimeoutError(
                code="scanner_timeout",
                operator_message=(
                    f"Сканирование не завершилось за {settings.timeout_seconds} секунд. "
                    "Процесс NAPS2 был принудительно остановлен. "
                    "Проверьте сканер и повторите попытку. Если ошибка повторяется, выполните диагностику."
                ),
                technical_message=(
                    f"NAPS2 timeout after {settings.timeout_seconds} seconds; "
                    f"process_stopped={process_stopped}; "
                    f"quarantine_path={quarantine_path}"
                ),
                output_path=output_path,
                stdout=stdout,
                stderr=stderr,
            ) from exc

    except KeyboardInterrupt as exc:
        duration_seconds = round(time.monotonic() - start_time, 3)

        logger.warning(
            "Scan interrupted by user operation_id=%s duration_seconds=%s output_path=%s pid=%s",
            operation_id,
            duration_seconds,
            output_path,
            process.pid if process else None,
        )

        process_stopped = True
        if process is not None:
            kill_process_tree(process=process, operation_id=operation_id)
            process_stopped = verify_process_stopped(
                process,
                operation_id=operation_id,
                max_wait_seconds=settings.verify_process_exit_seconds,
            )
            stdout, stderr = _collect_output_after_kill(
                process,
                timeout_seconds=settings.timeout_kill_grace_seconds,
            )

        quarantine_path = quarantine_untrusted_output(
            output_path,
            reason="scanner_interrupted",
            settings=settings,
            operation_id=operation_id,
        )

        if not process_stopped:
            raise ScannerProcessStillRunningError(
                code="scanner_process_still_running",
                operator_message=(
                    "NAPS2 не удалось остановить после прерывания. "
                    "Блокировка сканера сохранена; требуется ручная диагностика."
                ),
                technical_message=(
                    f"NAPS2 still alive after interruption; pid={process.pid if process else None}; "
                    f"quarantine_path={quarantine_path}; manual_recovery_required=1"
                ),
                output_path=output_path,
                stdout=stdout,
                stderr=stderr,
            ) from exc

        raise ScannerInterruptedError(
            code="scanner_interrupted",
            operator_message=(
                "Сканирование было прервано. Процесс NAPS2 принудительно остановлен, "
                "блокировка сканера должна быть освобождена. Проверьте устройство и повторите попытку."
            ),
            technical_message=(
                "KeyboardInterrupt while NAPS2 scan was running; "
                f"process_stopped={process_stopped}; quarantine_path={quarantine_path}"
            ),
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
        ) from exc

    except OSError as exc:
        raise ScannerProcessError(
            code="naps2_launch_error",
            operator_message="Не удалось запустить программу сканирования. Обратитесь к администратору.",
            technical_message=str(exc),
            output_path=output_path,
        ) from exc

    duration_seconds = round(time.monotonic() - start_time, 3)
    stdout = stdout or ""
    stderr = stderr or ""
    return_code = process.returncode if process else None

    logger.info(
        "NAPS2 finished operation_id=%s return_code=%s duration_seconds=%s output_path=%s stdout=%r stderr=%r",
        operation_id,
        return_code,
        duration_seconds,
        output_path,
        stdout,
        stderr,
    )

    known_error = classify_naps2_error(
        stdout=stdout,
        stderr=stderr,
        output_path=output_path,
        return_code=return_code,
    )

    if known_error:
        quarantine_path = quarantine_untrusted_output(
            output_path,
            reason=known_error.code,
            settings=settings,
            operation_id=operation_id,
        )
        _append_quarantine_info(known_error, quarantine_path)
        raise known_error

    if return_code != 0:
        quarantine_path = quarantine_untrusted_output(
            output_path,
            reason="naps2_process_error",
            settings=settings,
            operation_id=operation_id,
        )
        raise ScannerProcessError(
            code="naps2_process_error",
            operator_message="Программа сканирования завершилась с ошибкой. Повторите попытку или обратитесь к администратору.",
            technical_message=f"NAPS2 return code: {return_code}; quarantine_path={quarantine_path}",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )

def wait_until_file_is_stable(
    path: Path,
    required_checks: int,
    interval_seconds: float,
    max_wait_seconds: float = 10,
) -> None:
    deadline = time.monotonic() + max_wait_seconds
    last_size: int | None = None
    stable_count = 0

    while time.monotonic() < deadline:
        if path.is_file():
            current_size = path.stat().st_size

            if current_size > 0 and current_size == last_size:
                stable_count += 1

                if stable_count >= required_checks:
                    return
            else:
                stable_count = 0
                last_size = current_size

        time.sleep(interval_seconds)


def count_pdf_pages_if_possible(path: Path) -> int:
    """Строго читает PDF и возвращает количество страниц."""

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ScannerOutputInvalidError(
            code="pypdf_not_installed",
            operator_message="Не установлен обязательный модуль проверки PDF.",
            technical_message="Required dependency pypdf is not installed",
            output_path=path,
        ) from exc

    try:
        reader = PdfReader(str(path), strict=True)
        return len(reader.pages)
    except Exception as exc:
        raise ScannerOutputInvalidError(
            code="output_pdf_parse_error",
            operator_message="PDF-файл повреждён или имеет некорректную структуру.",
            technical_message=f"pypdf could not parse PDF: {exc}",
            output_path=path,
        ) from exc


def validate_pdf_output(output_path: Path, settings: ScannerSettings) -> None:
    wait_until_file_is_stable(
        path=output_path,
        required_checks=settings.stable_checks,
        interval_seconds=settings.stable_interval_seconds,
    )

    if not output_path.exists():
        raise ScannerOutputMissingError(
            code="output_missing",
            operator_message="Сканирование завершилось, но PDF-файл не был создан.",
            technical_message=f"Output file missing: {output_path}",
            output_path=output_path,
        )

    if not output_path.is_file():
        raise ScannerOutputInvalidError(
            code="output_not_file",
            operator_message="Результат сканирования некорректен. Обратитесь к администратору.",
            technical_message=f"Output path is not a file: {output_path}",
            output_path=output_path,
        )

    file_size = output_path.stat().st_size

    if file_size < settings.min_pdf_size_bytes:
        raise ScannerOutputInvalidError(
            code="output_too_small",
            operator_message="PDF-файл создан, но он слишком маленький. Возможно, сканирование прошло некорректно.",
            technical_message=f"Output file too small: {file_size} bytes",
            output_path=output_path,
        )

    with output_path.open("rb") as file:
        header = file.read(5)
        file.seek(max(0, file_size - 4096))
        tail = file.read()

    if header != b"%PDF-":
        raise ScannerOutputInvalidError(
            code="output_not_pdf",
            operator_message="Файл создан, но это не PDF. Обратитесь к администратору.",
            technical_message=f"Invalid PDF header: {header!r}",
            output_path=output_path,
        )

    if b"%%EOF" not in tail:
        raise ScannerOutputInvalidError(
            code="output_pdf_missing_eof",
            operator_message="PDF-файл не завершён и может быть повреждён.",
            technical_message="PDF EOF marker was not found in the final 4096 bytes",
            output_path=output_path,
        )

    page_count = count_pdf_pages_if_possible(output_path)
    logger.info("PDF page count checked output_path=%s page_count=%s", output_path, page_count)

    if page_count < settings.min_pdf_pages:
        raise ScannerOutputInvalidError(
            code="output_pdf_has_no_pages",
            operator_message="PDF-файл создан, но в нём нет страниц.",
            technical_message=f"PDF page count={page_count}, min_pdf_pages={settings.min_pdf_pages}",
            output_path=output_path,
        )


def scan_document(
    task_id: int | str,
    settings: ScannerSettings | None = None,
    operation_id: str | None = None,
    on_scan_start: Callable[[], None] | None = None,
) -> Path:
    if settings is None:
        settings = load_settings_from_env()

    logger.info("Scan requested operation_id=%s task_id=%s", operation_id, task_id)

    prepare_environment(settings)

    output_path = build_output_path(
        task_id=task_id,
        incoming_dir=Path(settings.incoming_dir),
    )

    command = build_naps2_command(
        settings=settings,
        output_path=output_path,
    )

    # The callback is deliberately invoked after all local preparation and
    # immediately before starting NAPS2. The document flow uses this instant
    # as the authoritative Europe/Moscow timestamp for the archive filename.
    if on_scan_start is not None:
        on_scan_start()

    run_naps2(
        command=command,
        settings=settings,
        output_path=output_path,
        operation_id=operation_id,
    )

    try:
        validate_pdf_output(
            output_path=output_path,
            settings=settings,
        )
    except ScannerError as exc:
        if isinstance(exc, (ScannerOutputInvalidError, ScannerOutputMissingError)):
            quarantine_path = quarantine_untrusted_output(
                output_path,
                reason=exc.code,
                settings=settings,
                operation_id=operation_id,
            )
            _append_quarantine_info(exc, quarantine_path)
        raise

    logger.info("Scan completed operation_id=%s task_id=%s output_path=%s", operation_id, task_id, output_path)

    return output_path
