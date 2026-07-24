from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
from unittest.mock import patch

from updater.errors import UpdateFailedRestoredError, UpdaterError
from updater.models import SemVer, VersionInfo
from updater.package import validate_package, extract_package
from updater.transaction import PreparedUpdate, UpdateTransaction
from updater.windows import UpdaterPaths
from tests.unit.updater_test_support import create_package


def make_paths(root: Path) -> UpdaterPaths:
    program_data = root / "ProgramData" / "Aerotech Docflow"
    temp_root = root / "Temp" / "Aerotech Docflow"
    return UpdaterPaths(
        install_dir=root / "Program Files" / "Aerotech Docflow",
        updater_dir=root / "Program Files" / "Aerotech Updater",
        program_data_dir=program_data,
        config_path=program_data / "config" / "config.toml",
        updater_log=program_data / "logs" / "updater.log",
        temp_root=temp_root,
        unpacked_dir=temp_root / "unpacked",
        rollback_dir=temp_root / "rollback",
        public_desktop=root / "Users" / "Public" / "Desktop",
    )


def prepare_fixture(root: Path) -> tuple[UpdaterPaths, PreparedUpdate]:
    paths = make_paths(root)
    (paths.install_dir / "app").mkdir(parents=True)
    (paths.install_dir / "app" / "aerotech-docflow.exe").write_bytes(b"old app")
    (paths.install_dir / "version.json").write_text(
        json.dumps({"version": "1.2.0", "config_schema": 2}), encoding="utf-8"
    )
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text("working-config", encoding="utf-8")
    paths.temp_root.mkdir(parents=True)
    package = validate_package(create_package(paths.temp_root, "1.3.0"))
    extract_package(package, paths.unpacked_dir)
    return paths, PreparedUpdate(
        installed=VersionInfo(SemVer.parse("1.2.0"), 2),
        package=package,
        incoming=root / "incoming",
    )


logger = logging.getLogger("updater-transaction-test")
logger.addHandler(logging.NullHandler())

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    paths, prepared = prepare_fixture(root)
    config_before = paths.config_path.read_bytes()
    idle_checks: list[Path] = []
    with (
        patch("updater.transaction.assert_scanner_idle", side_effect=lambda path: idle_checks.append(path)),
        patch("updater.transaction.stop_service"),
        patch("updater.transaction.start_service"),
        patch("updater.transaction.assert_docflow_process_stopped"),
        patch("updater.transaction.wait_health"),
    ):
        result = UpdateTransaction(paths, logger).apply(prepared, progress=lambda *_: None)
    assert result.installed_version == "1.3.0"
    assert len(idle_checks) == 2, "scanner must be checked after confirmation and after service stop"
    assert not paths.rollback_dir.exists()
    assert not Path(prepared.package.zip_path).exists()
    assert (paths.install_dir / "service" / "docflow-service.xml").is_file()
    assert paths.config_path.read_bytes() == config_before

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    paths, prepared = prepare_fixture(root)
    calls = 0

    def health(version: str) -> None:
        global calls
        calls += 1
        if version == "1.3.0":
            raise UpdaterError("POST_INSTALL_HEALTH_FAILED", "new health failed")

    with (
        patch("updater.transaction.assert_scanner_idle"),
        patch("updater.transaction.stop_service"),
        patch("updater.transaction.start_service"),
        patch("updater.transaction.assert_docflow_process_stopped"),
        patch("updater.transaction.service_state", return_value=1),
        patch("updater.transaction.wait_health", side_effect=health),
    ):
        try:
            UpdateTransaction(paths, logger).apply(prepared, progress=lambda *_: None)
        except UpdateFailedRestoredError as exc:
            assert exc.code == "POST_INSTALL_HEALTH_FAILED"
        else:
            raise AssertionError("failed new health must roll back")
    assert (paths.install_dir / "app" / "aerotech-docflow.exe").read_bytes() == b"old app"
    assert Path(prepared.package.zip_path).exists(), "failed package must remain for diagnostics"
    assert calls == 2

print("UPDATER TRANSACTION UNIT TEST OK")

