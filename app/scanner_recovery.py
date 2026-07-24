from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import csv
import io
import logging
import os
import re
import subprocess
import time

from app.locks import is_lock_stale, read_lock_info
from app.storage import is_reservation_stale, read_reservation_info


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
    lock_is_stale: bool
    naps2_processes: list[ProcessInfo]
    incoming_pf_files: list[Path]
    incoming_failed_runtime_files: list[Path]
    archive_tmp_files: list[Path]
    archive_reserve_files: list[Path]

    @property
    def has_risk_markers(self) -> bool:
        """
        Признаки, что после аварийного сценария нужна проверка.

        incoming_pf_files сами по себе не считаем риском: это может быть
        валидный скан, ожидающий retry_store_existing_scan() после ошибки storage.
        """

        return bool(
            self.lock_exists
            or self.naps2_processes
            or self.archive_tmp_files
            or self.archive_reserve_files
        )


@dataclass(frozen=True)
class StaleLockRecoveryResult:
    lock_path: Path
    lock_existed: bool
    removed: bool
    reason: str
    lock_info: dict[str, Any] | None


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


def find_incoming_failed_runtime_files(incoming_dir: Path, limit: int = 50) -> list[Path]:
    incoming_dir = Path(incoming_dir)
    runtime_dir = incoming_dir / "_failed_runtime"

    if not runtime_dir.exists() or not runtime_dir.is_dir():
        return []

    return sorted(
        [path for path in runtime_dir.rglob("*") if path.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]


def find_archive_artifacts(archive_root: Path, pattern: str, limit: int = 100) -> list[Path]:
    archive_root = Path(archive_root)

    if not archive_root.exists() or not archive_root.is_dir():
        return []

    return sorted(archive_root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def diagnose_scanner_state(
    incoming_dir: Path | str,
    archive_root: Path | str,
    *,
    lock_stale_after_seconds: int = 30 * 60,
) -> ScannerStateReport:
    incoming_dir = Path(incoming_dir)
    archive_root = Path(archive_root)
    lock_path = incoming_dir / ".scanner.lock"

    lock_info = read_lock_info(lock_path) if lock_path.exists() else None
    lock_stale = False

    if lock_info:
        lock_stale = is_lock_stale(
            lock_info=lock_info,
            stale_after_seconds=lock_stale_after_seconds,
        )

    return ScannerStateReport(
        incoming_dir=incoming_dir,
        archive_root=archive_root,
        lock_exists=lock_path.exists(),
        lock_info=lock_info,
        lock_is_stale=lock_stale,
        naps2_processes=list_naps2_processes(),
        incoming_pf_files=find_incoming_pf_files(incoming_dir),
        incoming_failed_runtime_files=find_incoming_failed_runtime_files(incoming_dir),
        archive_tmp_files=find_archive_artifacts(archive_root, "*.tmp"),
        archive_reserve_files=find_archive_artifacts(archive_root, "*.reserve"),
    )


def recover_stale_lock_if_safe(
    incoming_dir: Path | str,
    *,
    stale_after_seconds: int = 30 * 60,
) -> StaleLockRecoveryResult:
    """
    Безопасно удаляет только stale-lock.

    Это та же логика, которую основной scanner_lock применяет при следующем
    сканировании: если lock старый и процесс-владелец уже не жив — его можно снять.
    """

    incoming_dir = Path(incoming_dir)
    lock_path = incoming_dir / ".scanner.lock"

    if not lock_path.exists():
        return StaleLockRecoveryResult(
            lock_path=lock_path,
            lock_existed=False,
            removed=False,
            reason="lock_missing",
            lock_info=None,
        )

    lock_info = read_lock_info(lock_path)

    if not is_lock_stale(lock_info, stale_after_seconds=stale_after_seconds):
        return StaleLockRecoveryResult(
            lock_path=lock_path,
            lock_existed=True,
            removed=False,
            reason="lock_not_stale_or_owner_process_alive",
            lock_info=lock_info,
        )

    try:
        lock_path.unlink(missing_ok=True)
        logger.warning("Stale scanner lock removed by recovery diagnostics lock_path=%s lock_info=%s", lock_path, lock_info)
        return StaleLockRecoveryResult(
            lock_path=lock_path,
            lock_existed=True,
            removed=True,
            reason="stale_lock_removed",
            lock_info=lock_info,
        )

    except OSError as exc:
        logger.exception("Failed to remove stale scanner lock lock_path=%s error=%s", lock_path, exc)
        return StaleLockRecoveryResult(
            lock_path=lock_path,
            lock_existed=True,
            removed=False,
            reason=f"remove_error: {exc}",
            lock_info=lock_info,
        )


def remove_scanner_lock(
    incoming_dir: Path | str,
    *,
    stale_after_seconds: int = 30 * 60,
) -> bool:
    """Compatibility wrapper: remove only a proven stale lock, never force it."""

    return recover_stale_lock_if_safe(
        incoming_dir=incoming_dir,
        stale_after_seconds=stale_after_seconds,
    ).removed


def cleanup_archive_artifacts(
    archive_root: Path | str,
    *,
    stale_after_seconds: int = 30 * 60,
    remove_unowned_temp: bool = False,
) -> list[Path]:
    """
    Удаляет только подтверждённые stale-артефакты нашего приложения.

    `.reserve` должен содержать корректный JSON, указывать на соседний PDF и
    принадлежать завершившемуся процессу. `.tmp` не содержит owner metadata,
    поэтому по умолчанию никогда не удаляется автоматически. Его удаление
    требует remove_unowned_temp=True и проверки возраста.
    """

    archive_root = Path(archive_root)
    removed: list[Path] = []

    if not archive_root.exists() or not archive_root.is_dir():
        return removed

    resolved_root = archive_root.resolve(strict=False)
    candidates: list[Path] = []

    for path in archive_root.rglob("*.reserve"):
        if not path.is_file() or not path.name.startswith(".") or not path.name.endswith(".pdf.reserve"):
            continue
        info = read_reservation_info(path)
        if not info or info.get("invalid_reservation_file"):
            continue
        expected_destination = path.with_name(path.name[1:-len(".reserve")]).resolve(strict=False)
        try:
            recorded_destination = Path(str(info.get("destination_path", ""))).resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if recorded_destination != expected_destination:
            continue
        if resolved_root not in expected_destination.parents:
            continue
        if not is_reservation_stale(path, stale_after_seconds):
            continue
        candidates.append(path)

    if remove_unowned_temp:
        managed_temp_pattern = re.compile(r"^\..+\.pdf\.[0-9a-fA-F]{12}\.tmp$")
        for path in archive_root.rglob("*.tmp"):
            if not path.is_file() or not managed_temp_pattern.fullmatch(path.name):
                continue
            try:
                age_seconds = time.time() - path.stat().st_mtime
            except OSError:
                continue
            if age_seconds >= stale_after_seconds:
                candidates.append(path)

    # A crash between writing reservation JSON and publishing its hard link can
    # leave a fully written staging file. Unlike PDF copy .tmp files, it carries
    # owner metadata and can therefore be removed safely without an override.
    reservation_stage_pattern = re.compile(
        r"^\.\..+\.pdf\.reserve\.\d+\.[0-9a-fA-F]{12}\.tmp$"
    )
    for path in archive_root.rglob("*.tmp"):
        if not path.is_file() or not reservation_stage_pattern.fullmatch(path.name):
            continue
        info = read_reservation_info(path)
        if not info or info.get("invalid_reservation_file"):
            continue
        try:
            recorded_destination = Path(str(info.get("destination_path", ""))).resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if resolved_root not in recorded_destination.parents:
            continue
        if is_reservation_stale(path, stale_after_seconds):
            candidates.append(path)

    for path in candidates:
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            logger.warning("Failed to remove archive artifact path=%s error=%s", path, exc)

    return removed


def emergency_recover_after_interruption(
    incoming_dir: Path | str,
    archive_root: Path | str,
    *,
    kill_naps2: bool = True,
    remove_lock: bool = False,
    remove_stale_lock: bool = False,
    stale_after_seconds: int = 30 * 60,
    cleanup_artifacts: bool = False,
) -> dict[str, Any]:
    """
    Ручное восстановление после прерывания.

    По умолчанию убивает только NAPS2-процессы. Lock и .tmp/.reserve не удаляет
    без явного флага, чтобы случайно не повредить активную операцию.
    """

    before = diagnose_scanner_state(
        incoming_dir,
        archive_root,
        lock_stale_after_seconds=stale_after_seconds,
    )

    result: dict[str, Any] = {
        "before_has_risk_markers": before.has_risk_markers,
        "killed_naps2": [],
        "removed_lock": False,
        "stale_lock_recovery": None,
        "removed_archive_artifacts": [],
    }

    if kill_naps2:
        result["killed_naps2"] = kill_naps2_processes()

    if remove_stale_lock:
        stale_result = recover_stale_lock_if_safe(
            incoming_dir=incoming_dir,
            stale_after_seconds=stale_after_seconds,
        )
        result["stale_lock_recovery"] = {
            "lock_path": str(stale_result.lock_path),
            "lock_existed": stale_result.lock_existed,
            "removed": stale_result.removed,
            "reason": stale_result.reason,
            "lock_info": stale_result.lock_info,
        }

    if remove_lock:
        result["removed_lock"] = remove_scanner_lock(
            incoming_dir,
            stale_after_seconds=stale_after_seconds,
        )

    if cleanup_artifacts:
        result["removed_archive_artifacts"] = [
            str(path) for path in cleanup_archive_artifacts(archive_root)
        ]

    after = diagnose_scanner_state(
        incoming_dir,
        archive_root,
        lock_stale_after_seconds=stale_after_seconds,
    )
    result["after_has_risk_markers"] = after.has_risk_markers

    return result
