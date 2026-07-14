from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import locale
import logging
import os
import re
import secrets
import subprocess
import time

logger = logging.getLogger(__name__)


class ScannerError(RuntimeError):
    """Базовая ошибка сканирования."""

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


class ScannerTimeoutError(ScannerError):
    pass


class ScannerBusyError(ScannerError):
    pass


class ScannerConnectionError(ScannerError):
    pass


class ScannerNoPagesError(ScannerError):
    pass


class ScannerProcessError(ScannerError):
    pass


class ScannerOutputMissingError(ScannerError):
    pass


class ScannerOutputInvalidError(ScannerError):
    pass


@dataclass(frozen=True)
class ScannerSettings:
    """
    Настройки сканера.

    Основной режим сейчас — запуск через профиль NAPS2.
    Профиль хранит рабочие настройки драйвера, устройства, источника, DPI и цвета.
    """

    naps2_executable: Path | str = Path(r"C:\Program Files\NAPS2\NAPS2.Console.exe")
    incoming_dir: Path | str = Path(r"D:\incoming")

    # Точное имя профиля в NAPS2. Например: "CanonG600".
    profile_name: str | None = "CanonG600"

    # Используется только если profile_name = None.
    driver: str = "twain"
    device_name: str = "Canon G600 series Network"
    source: str | None = None
    dpi: int | None = None
    page_size: str | None = None
    bit_depth: str | None = None

    timeout_seconds: int = 120
    min_pdf_size_bytes: int = 100
    stable_checks: int = 2
    stable_interval_seconds: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "naps2_executable", Path(self.naps2_executable))
        object.__setattr__(self, "incoming_dir", Path(self.incoming_dir))


def load_settings_from_env() -> ScannerSettings:
    """Загрузить настройки из переменных окружения."""

    profile_name = os.getenv("NAPS2_PROFILE", "CanonG600").strip()
    if profile_name == "":
        profile_name = None

    source = os.getenv("SCANNER_SOURCE", "").strip()
    if source == "":
        source = None

    dpi = os.getenv("SCANNER_DPI", "").strip()
    page_size = os.getenv("SCANNER_PAGE_SIZE", "").strip()
    bit_depth = os.getenv("SCANNER_BIT_DEPTH", "").strip()

    return ScannerSettings(
        naps2_executable=os.getenv(
            "NAPS2_EXECUTABLE",
            r"C:\Program Files\NAPS2\NAPS2.Console.exe",
        ),
        incoming_dir=os.getenv("SCANNER_INCOMING_DIR", r"D:\incoming"),
        profile_name=profile_name,
        driver=os.getenv("SCANNER_DRIVER", "twain"),
        device_name=os.getenv("SCANNER_DEVICE_NAME", "Canon G600 series Network"),
        source=source,
        dpi=int(dpi) if dpi else None,
        page_size=page_size or None,
        bit_depth=bit_depth or None,
        timeout_seconds=int(os.getenv("SCANNER_TIMEOUT_SECONDS", "120")),
        min_pdf_size_bytes=int(os.getenv("SCANNER_MIN_PDF_SIZE_BYTES", "100")),
    )


def prepare_environment(settings: ScannerSettings) -> None:
    """Проверить, что NAPS2 существует и во временную папку можно писать."""

    if not settings.naps2_executable.is_file():
        raise ScannerExecutableNotFoundError(
            code="naps2_not_found",
            operator_message="Не найден NAPS2.Console.exe. Обратитесь к администратору.",
            technical_message=f"File not found: {settings.naps2_executable}",
        )

    try:
        settings.incoming_dir.mkdir(parents=True, exist_ok=True)

        test_file = settings.incoming_dir / ".scanner_write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)

    except OSError as exc:
        raise ScannerIncomingDirectoryError(
            code="incoming_dir_error",
            operator_message="Нет доступа к папке временных сканов. Обратитесь к администратору.",
            technical_message=str(exc),
        ) from exc


def build_output_path(task_id: int | str, incoming_dir: Path) -> Path:
    """
    Создать уникальный путь для временного PDF.

    Пример:
    D:\\incoming\\PF_TEST_001_20260714_154412_a1b2c3.pdf
    """

    raw_task_id = str(task_id).strip()

    if not raw_task_id:
        raise ScannerInvalidTaskIdError(
            code="invalid_task_id",
            operator_message="Не передан номер задачи для сканирования.",
            technical_message="task_id is empty",
        )

    safe_task_id = re.sub(r"[^A-Za-zА-Яа-я0-9_-]+", "_", raw_task_id).strip("_")

    if not safe_task_id:
        raise ScannerInvalidTaskIdError(
            code="invalid_task_id",
            operator_message="Некорректный номер задачи для сканирования.",
            technical_message=f"task_id={task_id!r}",
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)

    return incoming_dir / f"PF_{safe_task_id}_{timestamp}_{suffix}.pdf"


def build_naps2_command(settings: ScannerSettings, output_path: Path) -> list[str]:
    """Собрать команду запуска NAPS2."""

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


def _console_encoding() -> str:
    return locale.getpreferredencoding(False) or "utf-8"


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(_console_encoding(), errors="replace")
    return value


def classify_naps2_error(
    stdout: str,
    stderr: str,
    output_path: Path,
    return_code: int | None,
) -> ScannerError | None:
    """Распознать типовые ошибки NAPS2/Canon."""

    combined = f"{stdout}\n{stderr}".lower()

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


def run_naps2(command: list[str], settings: ScannerSettings, output_path: Path) -> None:
    """Запустить NAPS2.Console.exe и дождаться завершения."""

    logger.info("Запуск NAPS2: %s", command)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding=_console_encoding(),
            errors="replace",
            timeout=settings.timeout_seconds,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        raise ScannerTimeoutError(
            code="scanner_timeout",
            operator_message=f"Сканирование не завершилось за {settings.timeout_seconds} секунд. Возможно, драйвер ждёт действие оператора или сканер не отвечает.",
            technical_message=f"NAPS2 timeout after {settings.timeout_seconds} seconds",
            output_path=output_path,
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr),
        ) from exc

    except OSError as exc:
        raise ScannerProcessError(
            code="naps2_launch_error",
            operator_message="Не удалось запустить программу сканирования. Обратитесь к администратору.",
            technical_message=str(exc),
            output_path=output_path,
        ) from exc

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    known_error = classify_naps2_error(
        stdout=stdout,
        stderr=stderr,
        output_path=output_path,
        return_code=completed.returncode,
    )
    if known_error:
        raise known_error

    if completed.returncode != 0:
        raise ScannerProcessError(
            code="naps2_process_error",
            operator_message="Программа сканирования завершилась с ошибкой. Повторите попытку или обратитесь к администратору.",
            technical_message=f"NAPS2 return code: {completed.returncode}",
            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            return_code=completed.returncode,
        )

    logger.info("NAPS2 завершился успешно")


def wait_until_file_is_stable(
    path: Path,
    required_checks: int,
    interval_seconds: float,
    max_wait_seconds: float = 10,
) -> None:
    """Подождать, пока PDF перестанет изменяться по размеру."""

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


def validate_pdf_output(output_path: Path, settings: ScannerSettings) -> None:
    """Проверить, что NAPS2 создал нормальный PDF."""

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

    if header != b"%PDF-":
        raise ScannerOutputInvalidError(
            code="output_not_pdf",
            operator_message="Файл создан, но это не PDF. Обратитесь к администратору.",
            technical_message=f"Invalid PDF header: {header!r}",
            output_path=output_path,
        )


def scan_document(
    task_id: int | str,
    settings: ScannerSettings | None = None,
) -> Path:
    """
    Главная функция модуля сканера.

    На вход: task_id.
    На выход: путь к созданному PDF.
    """

    if settings is None:
        settings = load_settings_from_env()

    prepare_environment(settings)

    output_path = build_output_path(
        task_id=task_id,
        incoming_dir=settings.incoming_dir,
    )

    command = build_naps2_command(
        settings=settings,
        output_path=output_path,
    )

    run_naps2(
        command=command,
        settings=settings,
        output_path=output_path,
    )

    validate_pdf_output(
        output_path=output_path,
        settings=settings,
    )

    logger.info("Сканирование завершено: %s", output_path)
    return output_path
