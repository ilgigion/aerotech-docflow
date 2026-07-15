from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import csv
import io
import logging
import os
import subprocess

from app.locks import read_lock_info


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessInfo:
    image_name: str
    pid: int
    session_name: str = ""
    memory_usage: str = ""


@dataclass(frozen=True)
class ScannerStateReport:
    incoming_dir: Path
    archive_root: Path
    lock_exists: bool
    lock_info: dict[str, Any] | None
    naps2_processes: list[ProcessInfo]
    incoming_pf_files: list[Path]
    archive_tmp_files: list[Path]
    archive_reserve_files: list[Path]

    @property
    def has_risk_markers(self) -> bool:
        return bool(
            self.lock_exists
            or self.naps2_processes
            or self.archive_tmp_files
            or self.archive_reserve_files
        )


def _run_command(command: list[str], timeout_seconds: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def list_processes_by_image_names(image_names: list[str]) -> list[ProcessInfo]:
    """
    Возвращает процессы Windows по именам образов через tasklist.

    Не используем psutil, чтобы не добавлять зависимость.
    На не-Windows вернёт пустой список.
    """

    if os.name != "nt":
        return []

    result: list[ProcessInfo] = []

    for image_name in image_names:
        completed = _run_command(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"]
        )

        output = (completed.stdout or "").strip()
        if not output or "INFO:" in output.upper():
            continue

        reader = csv.reader(io.StringIO(output))
        for row in reader:
            if len(row) < 2:
                continue

            try:
                pid = int(row[1])
            except ValueError:
                continue

            result.append(
                ProcessInfo(
                    image_name=row[0],
                    pid=pid,
                    session_name=row[2] if len(row) > 2 else "",
                    memory_usage=row[4] if len(row) > 4 else "",
                )
            )

    return result


def list_naps2_processes() -> list[ProcessInfo]:
    return list_processes_by_image_names(
        [
            "NAPS2.Console.exe",
            "NAPS2.exe",
        ]
    )


def kill_naps2_processes() -> list[str]:
    """
    Принудительно завершает все процессы NAPS2.

    Использовать для ручного восстановления после прерывания/зависания.
    В штатном процессе scanner.py убивает только свой конкретный PID.
    """

    messages: list[str] = []

    if os.name != "nt":
        return ["kill_naps2_processes поддержан только на Windows"]

    for image_name in ["NAPS2.Console.exe", "NAPS2.exe"]:
        completed = _run_command(
            ["taskkill", "/IM", image_name, "/T", "/F"],
            timeout_seconds=20,
        )

        messages.append(
            f"{image_name}: return_code={completed.returncode}; stdout={completed.stdout.strip()!r}; stderr={completed.stderr.strip()!r}"
        )

    return messages


def find_incoming_pf_files(incoming_dir: Path, limit: int = 50) -> list[Path]:
    incoming_dir = Path(incoming_dir)

    if not incoming_dir.exists() or not incoming_dir.is_dir():
        return []

    return sorted(incoming_dir.glob("PF_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def find_archive_artifacts(archive_root: Path, pattern: str, limit: int = 100) -> list[Path]:
    archive_root = Path(archive_root)

    if not archive_root.exists() or not archive_root.is_dir():
        return []

    return sorted(archive_root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def diagnose_scanner_state(
    incoming_dir: Path | str = Path(r"D:\incoming"),
    archive_root: Path | str = Path(r"D:\archive_test"),
) -> ScannerStateReport:
    incoming_dir = Path(incoming_dir)
    archive_root = Path(archive_root)
    lock_path = incoming_dir / ".scanner.lock"

    lock_info = read_lock_info(lock_path) if lock_path.exists() else None

    return ScannerStateReport(
        incoming_dir=incoming_dir,
        archive_root=archive_root,
        lock_exists=lock_path.exists(),
        lock_info=lock_info,
        naps2_processes=list_naps2_processes(),
        incoming_pf_files=find_incoming_pf_files(incoming_dir),
        archive_tmp_files=find_archive_artifacts(archive_root, "*.tmp"),
        archive_reserve_files=find_archive_artifacts(archive_root, "*.reserve"),
    )


def remove_scanner_lock(incoming_dir: Path | str = Path(r"D:\incoming")) -> bool:
    lock_path = Path(incoming_dir) / ".scanner.lock"

    if not lock_path.exists():
        return False

    lock_path.unlink()
    return True


def cleanup_archive_artifacts(
    archive_root: Path | str = Path(r"D:\archive_test"),
) -> list[Path]:
    """
    Удаляет .tmp и .reserve в архиве.

    Использовать только когда точно нет активного сканирования и NAPS2-процессов.
    """

    archive_root = Path(archive_root)
    removed: list[Path] = []

    if not archive_root.exists() or not archive_root.is_dir():
        return removed

    for path in list(archive_root.rglob("*.tmp")) + list(archive_root.rglob("*.reserve")):
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            logger.warning("Failed to remove archive artifact path=%s error=%s", path, exc)

    return removed


def emergency_recover_after_interruption(
    incoming_dir: Path | str = Path(r"D:\incoming"),
    archive_root: Path | str = Path(r"D:\archive_test"),
    *,
    kill_naps2: bool = True,
    remove_lock: bool = False,
    cleanup_artifacts: bool = False,
) -> dict[str, Any]:
    """
    Ручное восстановление после прерывания.

    По умолчанию убивает только NAPS2-процессы. Lock и .tmp/.reserve не удаляет
    без явного флага, чтобы случайно не повредить активную операцию.
    """

    before = diagnose_scanner_state(incoming_dir, archive_root)

    result: dict[str, Any] = {
        "before_has_risk_markers": before.has_risk_markers,
        "killed_naps2": [],
        "removed_lock": False,
        "removed_archive_artifacts": [],
    }

    if kill_naps2:
        result["killed_naps2"] = kill_naps2_processes()

    if remove_lock:
        result["removed_lock"] = remove_scanner_lock(incoming_dir)

    if cleanup_artifacts:
        result["removed_archive_artifacts"] = [
            str(path) for path in cleanup_archive_artifacts(archive_root)
        ]

    after = diagnose_scanner_state(incoming_dir, archive_root)
    result["after_has_risk_markers"] = after.has_risk_markers

    return result
