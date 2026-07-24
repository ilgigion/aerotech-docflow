from __future__ import annotations

from contextlib import contextmanager
import csv
import ctypes
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable, Iterator
from urllib.request import ProxyHandler, build_opener
import xml.etree.ElementTree as ET

from updater.errors import UpdaterError


SERVICE_NAME = "AerotechDocflow"
MUTEX_NAME = r"Global\AerotechDocflowUpdater"
HEALTH_URL = "http://127.0.0.1:8000/health"
SERVICE_STATE_NAMES = {
    1: "STOPPED",
    2: "START_PENDING",
    3: "STOP_PENDING",
    4: "RUNNING",
    5: "CONTINUE_PENDING",
    6: "PAUSE_PENDING",
    7: "PAUSED",
}


def _service_state_name(value: int | None) -> str:
    if value is None:
        return "NOT_INSTALLED"
    return SERVICE_STATE_NAMES.get(value, f"UNKNOWN({value})")


def _compact_process_output(value: str, *, limit: int = 1000) -> str:
    text = " ".join(value.split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _system_drive_root(value: str) -> Path:
    match = re.fullmatch(r"([A-Za-z]):[\\/]*", value.strip())
    if not match:
        raise UpdaterError(
            "PATH_RESOLUTION_FAILED",
            f"Некорректный абсолютный SystemDrive: {value!r}.",
        )
    return Path(f"{match.group(1).upper()}:\\")


@dataclass(frozen=True)
class UpdaterPaths:
    install_dir: Path
    updater_dir: Path
    program_data_dir: Path
    config_path: Path
    updater_log: Path
    temp_root: Path
    unpacked_dir: Path
    rollback_dir: Path
    public_desktop: Path

    @classmethod
    def production(cls) -> "UpdaterPaths":
        if os.name != "nt":
            raise UpdaterError("WINDOWS_REQUIRED", "Updater поддерживает только Windows.")
        program_files = os.environ.get("ProgramW6432") if _is_64bit_windows() else os.environ.get("ProgramFiles")
        if not program_files:
            raise UpdaterError("PATH_RESOLUTION_FAILED", "Не удалось определить Program Files.")
        program_files_path = Path(program_files).resolve(strict=False)
        if _is_64bit_windows() and program_files_path.name.casefold() == "program files (x86)":
            raise UpdaterError("PATH_RESOLUTION_FAILED", "Запрещён путь Program Files (x86).")
        program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Aerotech Docflow"
        temp_root = _system_drive_root(os.environ.get("SystemDrive", "C:")) / "Temp" / "Aerotech Docflow"
        public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
        return cls(
            install_dir=program_files_path / "Aerotech Docflow",
            updater_dir=program_files_path / "Aerotech Updater",
            program_data_dir=program_data,
            config_path=program_data / "config" / "config.toml",
            updater_log=program_data / "logs" / "updater.log",
            temp_root=temp_root,
            unpacked_dir=temp_root / "unpacked",
            rollback_dir=temp_root / "rollback",
            public_desktop=public / "Desktop",
        )


def _is_64bit_windows() -> bool:
    return bool(os.environ.get("ProgramW6432") or os.environ.get("PROCESSOR_ARCHITEW6432"))


def ensure_administrator() -> None:
    if os.name != "nt" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise UpdaterError("ADMIN_REQUIRED", "Запустите программу с правами администратора.")


@contextmanager
def single_instance() -> Iterator[None]:
    if os.name != "nt":
        yield
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise UpdaterError("MUTEX_FAILED", "Не удалось создать блокировку updater.")
    try:
        if kernel32.GetLastError() == 183:
            raise UpdaterError("UPDATER_ALREADY_RUNNING", "Другой экземпляр updater уже запущен.")
        yield
    finally:
        kernel32.CloseHandle(handle)


def configure_logging(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("aerotech_updater")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _system_executable(name: str) -> str:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    executable = system_root / "System32" / name
    return str(executable)


def _windows_oem_encoding() -> str:
    if os.name == "nt":
        try:
            code_page = int(ctypes.windll.kernel32.GetOEMCP())
            if code_page > 0:
                return f"cp{code_page}"
        except (AttributeError, OSError, ValueError):
            pass
    return "utf-8"


def _run(
    command: list[str],
    *,
    timeout: int = 60,
    encoding: str = "utf-8",
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdaterError("PROCESS_EXECUTION_FAILED", f"Не удалось выполнить {command[0]}: {exc}") from exc


def service_state() -> int | None:
    if os.name != "nt":
        raise UpdaterError("WINDOWS_REQUIRED", "Проверка службы доступна только на Windows.")

    class ServiceStatusProcess(ctypes.Structure):
        _fields_ = [
            ("service_type", ctypes.c_ulong),
            ("current_state", ctypes.c_ulong),
            ("controls_accepted", ctypes.c_ulong),
            ("win32_exit_code", ctypes.c_ulong),
            ("service_specific_exit_code", ctypes.c_ulong),
            ("check_point", ctypes.c_ulong),
            ("wait_hint", ctypes.c_ulong),
            ("process_id", ctypes.c_ulong),
            ("service_flags", ctypes.c_ulong),
        ]

    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.OpenSCManagerW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    advapi32.OpenSCManagerW.restype = ctypes.c_void_p
    advapi32.OpenServiceW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
    advapi32.OpenServiceW.restype = ctypes.c_void_p
    advapi32.QueryServiceStatusEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    advapi32.QueryServiceStatusEx.restype = ctypes.c_int
    advapi32.CloseServiceHandle.argtypes = [ctypes.c_void_p]
    advapi32.CloseServiceHandle.restype = ctypes.c_int
    manager = advapi32.OpenSCManagerW(None, None, 0x0001)
    if not manager:
        raise UpdaterError("SERVICE_QUERY_FAILED", "Не удалось открыть Service Control Manager.")
    service = None
    try:
        service = advapi32.OpenServiceW(manager, SERVICE_NAME, 0x0004)
        if not service:
            error = ctypes.get_last_error()
            if error == 1060:
                return None
            raise UpdaterError("SERVICE_QUERY_FAILED", f"Не удалось открыть службу; Windows error={error}.")
        status = ServiceStatusProcess()
        needed = ctypes.c_ulong()
        success = advapi32.QueryServiceStatusEx(
            service,
            0,
            ctypes.byref(status),
            ctypes.sizeof(status),
            ctypes.byref(needed),
        )
        if not success:
            raise UpdaterError(
                "SERVICE_QUERY_FAILED",
                f"QueryServiceStatusEx завершился ошибкой {ctypes.get_last_error()}.",
            )
        return int(status.current_state)
    finally:
        if service:
            advapi32.CloseServiceHandle(service)
        advapi32.CloseServiceHandle(manager)


def _wait_service(
    expected: int,
    timeout_seconds: int,
    *,
    report: Callable[[str], None] | None = None,
    fail_if_stopped: bool = False,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    stopped_observations = 0
    while time.monotonic() < deadline:
        attempt += 1
        state = service_state()
        if report is not None:
            report(
                f"SCM: ожидание {_service_state_name(expected)}, "
                f"проверка {attempt}, сейчас {_service_state_name(state)}."
            )
        if state == expected:
            return
        if fail_if_stopped and state == 1:
            stopped_observations += 1
            if stopped_observations >= 2:
                raise UpdaterError(
                    "SERVICE_START_FAILED",
                    "Служба вернулась в STOPPED сразу после команды запуска.",
                )
        else:
            stopped_observations = 0
        time.sleep(1)
    raise UpdaterError(
        "SERVICE_TIMEOUT",
        f"Служба не перешла в состояние {_service_state_name(expected)} за {timeout_seconds} секунд.",
    )


def stop_service() -> None:
    state = service_state()
    if state is None:
        raise UpdaterError("SERVICE_NOT_INSTALLED", f"Служба {SERVICE_NAME} не установлена.")
    if state == 1:
        return
    if state == 3:
        _wait_service(1, 30)
        return
    completed = _run(
        [_system_executable("sc.exe"), "stop", SERVICE_NAME],
        encoding=_windows_oem_encoding(),
    )
    if completed.returncode != 0:
        raise UpdaterError("SERVICE_STOP_FAILED", "Не удалось остановить службу AerotechDocflow.")
    _wait_service(1, 30)


def start_service(*, report: Callable[[str], None] | None = None) -> None:
    state = service_state()
    if report is not None:
        report(f"SCM: состояние перед запуском — {_service_state_name(state)}.")
    if state is None:
        raise UpdaterError("SERVICE_NOT_INSTALLED", f"Служба {SERVICE_NAME} не установлена.")
    if state == 4:
        if report is not None:
            report("SCM: служба уже находится в RUNNING.")
        return
    if state == 2:
        _wait_service(4, 30, report=report, fail_if_stopped=True)
        return
    completed = _run(
        [_system_executable("sc.exe"), "start", SERVICE_NAME],
        encoding=_windows_oem_encoding(),
    )
    stdout = _compact_process_output(completed.stdout)
    stderr = _compact_process_output(completed.stderr)
    if report is not None:
        report(
            f"sc.exe start: exit={completed.returncode}; "
            f"stdout={stdout or '<empty>'}; stderr={stderr or '<empty>'}."
        )
    if completed.returncode != 0:
        raise UpdaterError(
            "SERVICE_START_FAILED",
            "Не удалось запустить службу AerotechDocflow: "
            f"sc.exe exit={completed.returncode}; stdout={stdout or '<empty>'}; "
            f"stderr={stderr or '<empty>'}.",
        )
    _wait_service(4, 30, report=report, fail_if_stopped=True)


def process_names() -> list[str]:
    completed = _run(
        [_system_executable("tasklist.exe"), "/FO", "CSV", "/NH"],
        encoding=_windows_oem_encoding(),
    )
    if completed.returncode != 0:
        raise UpdaterError("PROCESS_QUERY_FAILED", "Не удалось получить список процессов.")
    names: list[str] = []
    for row in csv.reader(completed.stdout.splitlines()):
        if row:
            names.append(row[0])
    return names


def collect_service_diagnostics(paths: UpdaterPaths) -> dict[str, object]:
    wrapper_path = paths.install_dir / "service" / "docflow-service.exe"
    xml_path = paths.install_dir / "service" / "docflow-service.xml"
    result: dict[str, object] = {
        "wrapper_path": str(wrapper_path),
        "wrapper_exists": wrapper_path.is_file(),
        "xml_path": str(xml_path),
        "xml_exists": xml_path.is_file(),
    }
    try:
        result["service_state"] = _service_state_name(service_state())
    except Exception as exc:
        result["service_state_error"] = str(exc)

    try:
        root = ET.parse(xml_path).getroot()
        result["xml"] = {
            "id": root.findtext("id"),
            "executable": root.findtext("executable"),
            "arguments": root.findtext("arguments"),
            "workingdirectory": root.findtext("workingdirectory"),
            "logpath": root.findtext("logpath"),
        }
    except Exception as exc:
        result["xml_error"] = str(exc)

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}",
        ) as key:
            result["scm"] = {
                "image_path": winreg.QueryValueEx(key, "ImagePath")[0],
                "start_name": winreg.QueryValueEx(key, "ObjectName")[0],
            }
    except Exception as exc:
        result["scm_error"] = str(exc)

    try:
        query = _run(
            [_system_executable("sc.exe"), "queryex", SERVICE_NAME],
            encoding=_windows_oem_encoding(),
        )
        result["sc_queryex"] = {
            "exit_code": query.returncode,
            "stdout": _compact_process_output(query.stdout),
            "stderr": _compact_process_output(query.stderr),
        }
    except Exception as exc:
        result["sc_queryex_error"] = str(exc)

    try:
        completed = _run(
            [_system_executable("tasklist.exe"), "/FO", "CSV", "/NH"],
            encoding=_windows_oem_encoding(),
        )
        processes: list[dict[str, str]] = []
        for row in csv.reader(completed.stdout.splitlines()):
            if len(row) >= 2 and row[0].casefold() in {
                "aerotech-docflow.exe",
                "docflow-service.exe",
            }:
                processes.append({"name": row[0], "pid": row[1]})
        result["relevant_processes"] = processes
    except Exception as exc:
        result["process_query_error"] = str(exc)

    log_dir = paths.program_data_dir / "service-logs"
    try:
        logs = sorted(
            (path for path in log_dir.glob("docflow-service*.log") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if logs:
            latest = logs[0]
            with latest.open("rb") as stream:
                size = latest.stat().st_size
                stream.seek(max(0, size - 16 * 1024))
                tail = stream.read().decode("utf-8", errors="replace")
            result["latest_wrapper_log"] = {
                "path": str(latest),
                "tail": tail[-8000:],
            }
    except Exception as exc:
        result["wrapper_log_error"] = str(exc)

    return result


def assert_no_naps2() -> None:
    matches = sorted(name for name in process_names() if name.casefold().startswith("naps2"))
    if matches:
        raise UpdaterError("SCANNER_ACTIVE", f"NAPS2 сейчас запущен: {', '.join(matches)}")


def assert_docflow_process_stopped() -> None:
    matches = [name for name in process_names() if name.casefold() == "aerotech-docflow.exe"]
    if matches:
        raise UpdaterError("APP_PROCESS_STILL_RUNNING", "Процесс aerotech-docflow.exe не остановился.")


def run_json_command(executable: Path, config: Path, command: str, *, timeout: int = 60) -> dict:
    completed = _run([str(executable), "--config", str(config), command, "--ascii"] if command == "show-config" else [str(executable), "--config", str(config), command], timeout=timeout)
    if completed.returncode != 0:
        raise UpdaterError(
            "APPLICATION_COMMAND_FAILED",
            f"Команда {command} завершилась с кодом {completed.returncode}.",
        )
    try:
        payload = json.loads(completed.stdout)
    except ValueError as exc:
        raise UpdaterError("APPLICATION_COMMAND_FAILED", f"Команда {command} вернула не JSON.") from exc
    if not isinstance(payload, dict):
        raise UpdaterError("APPLICATION_COMMAND_FAILED", f"Команда {command} вернула неверный JSON.")
    return payload


def incoming_from_config(executable: Path, config: Path) -> Path:
    payload = run_json_command(executable, config, "show-config")
    if not payload.get("config_loaded"):
        raise UpdaterError("CONFIG_NOT_LOADED", "Рабочий config.toml не был загружен.")
    effective = payload.get("effective_environment")
    if not isinstance(effective, dict):
        raise UpdaterError("CONFIG_NOT_LOADED", "Команда show-config не вернула настройки.")
    incoming = effective.get("SCANNER_INCOMING_DIR")
    if not isinstance(incoming, str) or not incoming.strip():
        raise UpdaterError("CONFIG_NOT_LOADED", "В конфиге отсутствует scanner.incoming_dir.")
    path = Path(incoming)
    if not path.is_absolute():
        raise UpdaterError("CONFIG_NOT_LOADED", "scanner.incoming_dir должен быть абсолютным путём.")
    return path.resolve(strict=False)


def run_preflight(executable: Path, config: Path) -> None:
    payload = run_json_command(executable, config, "preflight", timeout=120)
    if payload.get("status") != "ok":
        raise UpdaterError("PREFLIGHT_FAILED", "Новая версия не прошла preflight.")


def assert_scanner_idle(incoming: Path) -> None:
    assert_no_naps2()
    lock_path = incoming / ".scanner.lock"
    if lock_path.exists():
        raise UpdaterError("SCANNER_ACTIVE", f"Обнаружен scanner lock: {lock_path}")


def wait_health(
    expected_version: str,
    *,
    attempts: int = 10,
    interval: float = 2.0,
    report: Callable[[str], None] | None = None,
) -> dict:
    opener = build_opener(ProxyHandler({}))
    last_error = "нет ответа"
    for attempt in range(1, attempts + 1):
        if report is not None:
            report(f"/health: попытка {attempt}/{attempts}, ожидается версия {expected_version}.")
        try:
            with opener.open(HEALTH_URL, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if (
                isinstance(payload, dict)
                and payload.get("status") == "ok"
                and payload.get("service") == "aerotech-docflow"
                and payload.get("version") == expected_version
            ):
                if report is not None:
                    report(f"/health: получен status=ok, version={expected_version}.")
                return payload
            last_error = f"неожиданный ответ: {payload!r}"
        except Exception as exc:
            last_error = str(exc)
        if report is not None:
            report(f"/health пока не готов: {_compact_process_output(last_error, limit=300)}")
        time.sleep(interval)
    raise UpdaterError(
        "POST_INSTALL_HEALTH_FAILED",
        f"Служба не прошла /health для версии {expected_version}: {last_error}",
    )


def read_current_health() -> dict | None:
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(HEALTH_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("status") != "ok" or payload.get("service") != "aerotech-docflow":
        return None
    return payload


def probe_version_command(executable: Path) -> str | None:
    for arguments in (["--version"], ["version"]):
        completed = _run([str(executable), *arguments], timeout=10)
        if completed.returncode != 0:
            continue
        output = completed.stdout.strip()
        if re.fullmatch(r"(?:v)?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", output):
            return output.removeprefix("v")
        try:
            payload = json.loads(output)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("version"), str):
            return payload["version"]
    return None


def create_shortcut(target: Path, shortcut: Path) -> None:
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    escaped_target = str(target).replace("'", "''")
    escaped_shortcut = str(shortcut).replace("'", "''")
    command = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('"
        + escaped_shortcut
        + "');$s.TargetPath='"
        + escaped_target
        + "';$s.WorkingDirectory='"
        + str(target.parent).replace("'", "''")
        + "';$s.Description='Обновить Aerotech Docflow';$s.Save()"
    )
    completed = _run(
        [
            _system_executable("WindowsPowerShell\\v1.0\\powershell.exe"),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ]
    )
    if completed.returncode != 0 or not shortcut.is_file():
        raise UpdaterError("SHORTCUT_FAILED", "Не удалось создать ярлык updater.")
