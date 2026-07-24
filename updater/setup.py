from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from updater import console
from updater.errors import UpdaterError
from updater.models import SemVer, VersionInfo
from updater.transaction import read_version_file, write_version_file_atomic
from updater.windows import (
    UpdaterPaths,
    configure_logging,
    create_shortcut,
    ensure_administrator,
    probe_version_command,
    read_current_health,
    run_json_command,
)


LEGACY_CONFIG_SCHEMA = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _embedded_updater() -> Path:
    explicit = os.environ.get("AEROTECH_UPDATER_SOURCE", "").strip()
    if explicit:
        return Path(explicit).resolve(strict=False)
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / "AerotechUpdater.exe"


def _determine_legacy_version(paths: UpdaterPaths) -> VersionInfo:
    executable = paths.install_dir / "app" / "aerotech-docflow.exe"
    if not executable.is_file():
        raise UpdaterError("INSTALLATION_INVALID", f"Существующий EXE не найден: {executable}")
    if not paths.config_path.is_file():
        raise UpdaterError("CONFIG_NOT_FOUND", f"Рабочий config.toml не найден: {paths.config_path}")

    sources: dict[str, str] = {}
    command_version = probe_version_command(executable)
    if command_version:
        sources["executable"] = command_version

    try:
        config_report = run_json_command(executable, paths.config_path, "show-config")
        overrides = config_report.get("overridden_by_environment")
        effective = config_report.get("effective_environment")
        config_version = effective.get("DOCFLOW_VERSION") if isinstance(effective, dict) else None
        if (
            config_report.get("config_loaded") is True
            and isinstance(overrides, list)
            and "DOCFLOW_VERSION" not in overrides
            and isinstance(config_version, str)
        ):
            SemVer.parse(config_version)
            sources["config"] = config_version
    except Exception:
        pass

    health = read_current_health()
    health_version = health.get("version") if health else None
    if isinstance(health_version, str):
        try:
            SemVer.parse(health_version)
            sources["health"] = health_version
        except UpdaterError:
            pass

    unique = set(sources.values())
    independently_confirmed = "executable" in sources or {"config", "health"}.issubset(sources)
    if len(unique) != 1 or not independently_confirmed:
        details = ", ".join(f"{name}={value}" for name, value in sorted(sources.items())) or "источники отсутствуют"
        raise UpdaterError(
            "LEGACY_VERSION_UNKNOWN",
            "Невозможно однозначно определить версию существующей установки v1.2. "
            f"Проверенные источники: {details}.",
        )
    return VersionInfo(SemVer.parse(unique.pop()), LEGACY_CONFIG_SCHEMA)


def install() -> int:
    console.prepare_console()
    print("Aerotech Updater Setup")
    print()
    logger = None
    paths = None
    created_version = False
    updater_backup: Path | None = None
    target: Path | None = None
    target_installed = False
    shortcut: Path | None = None
    shortcut_backup: Path | None = None
    try:
        ensure_administrator()
        paths = UpdaterPaths.production()
        source = _embedded_updater()
        if not source.is_file() or source.stat().st_size == 0:
            raise UpdaterError("UPDATER_PAYLOAD_MISSING", f"AerotechUpdater.exe не найден: {source}")

        version_path = paths.install_dir / "version.json"
        if version_path.is_file():
            installed_version = read_version_file(version_path)
            pending_version: VersionInfo | None = None
        else:
            installed_version = _determine_legacy_version(paths)
            pending_version = installed_version

        config_hash_before = _sha256(paths.config_path)
        paths.temp_root.mkdir(parents=True, exist_ok=True)
        paths.updater_log.parent.mkdir(parents=True, exist_ok=True)
        logger = configure_logging(paths.updater_log)
        logger.info("Updater setup started detected_docflow_version=%s", installed_version.version)

        paths.updater_dir.mkdir(parents=True, exist_ok=True)
        target = paths.updater_dir / "AerotechUpdater.exe"
        temporary = paths.updater_dir / "AerotechUpdater.exe.new"
        updater_backup = paths.updater_dir / "AerotechUpdater.exe.previous"
        temporary.unlink(missing_ok=True)
        updater_backup.unlink(missing_ok=True)
        shutil.copyfile(source, temporary)
        if _sha256(source) != _sha256(temporary):
            raise UpdaterError("UPDATER_COPY_FAILED", "SHA-256 скопированного updater не совпадает.")
        if target.exists():
            os.replace(target, updater_backup)
        os.replace(temporary, target)
        target_installed = True

        if pending_version is not None:
            write_version_file_atomic(version_path, pending_version)
            created_version = True

        shortcut = paths.public_desktop / "Обновить Aerotech Docflow.lnk"
        shortcut_backup = shortcut.with_name(shortcut.name + ".previous")
        shortcut_backup.unlink(missing_ok=True)
        if shortcut.exists():
            shutil.copyfile(shortcut, shortcut_backup)
        create_shortcut(target, shortcut)
        if _sha256(paths.config_path) != config_hash_before:
            raise UpdaterError("CONFIG_CHANGED", "Setup обнаружил изменение рабочего config.toml.")

        updater_backup.unlink(missing_ok=True)
        shortcut_backup.unlink(missing_ok=True)
        logger.info("Updater setup completed target=%s shortcut=%s", target, shortcut)
        console.ok(f"Updater установлен: {target}")
        console.ok(f"Ярлык создан: {shortcut}")
        console.ok(f"Aerotech Docflow: {installed_version.version}")
        return 0
    except UpdaterError as exc:
        if logger:
            logger.error("Updater setup failed code=%s reason=%s", exc.code, exc.message, exc_info=True)
        if paths and target:
            if updater_backup and updater_backup.exists():
                target.unlink(missing_ok=True)
                os.replace(updater_backup, target)
            elif target_installed:
                target.unlink(missing_ok=True)
        if shortcut:
            if shortcut_backup and shortcut_backup.exists():
                shortcut.unlink(missing_ok=True)
                os.replace(shortcut_backup, shortcut)
            else:
                shortcut.unlink(missing_ok=True)
        if created_version and paths:
            (paths.install_dir / "version.json").unlink(missing_ok=True)
        print("Updater не установлен.")
        print(f"Причина: {exc.message}")
        print(f"Код ошибки: {exc.code}")
        return 1
    except Exception as exc:
        if logger:
            logger.critical("Unexpected setup failure: %s", exc, exc_info=True)
        if paths and target:
            if updater_backup and updater_backup.exists():
                target.unlink(missing_ok=True)
                os.replace(updater_backup, target)
            elif target_installed:
                target.unlink(missing_ok=True)
        if shortcut:
            if shortcut_backup and shortcut_backup.exists():
                shortcut.unlink(missing_ok=True)
                os.replace(shortcut_backup, shortcut)
            else:
                shortcut.unlink(missing_ok=True)
        if created_version and paths:
            (paths.install_dir / "version.json").unlink(missing_ok=True)
        print("Updater не установлен.")
        print(f"Непредвиденная ошибка: {exc}")
        print("Код ошибки: UNEXPECTED_SETUP_ERROR")
        return 2
    finally:
        if paths:
            print()
            print(f"Подробный лог: {paths.updater_log}")
        console.wait_for_key()


if __name__ == "__main__":
    raise SystemExit(install())
