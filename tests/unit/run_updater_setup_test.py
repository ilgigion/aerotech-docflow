from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

from updater.errors import UpdaterError
from updater.setup import _determine_legacy_version
from updater.windows import UpdaterPaths


def paths_for(root: Path) -> UpdaterPaths:
    data = root / "ProgramData" / "Aerotech Docflow"
    temp_root = root / "Temp" / "Aerotech Docflow"
    return UpdaterPaths(
        install_dir=root / "Program Files" / "Aerotech Docflow",
        updater_dir=root / "Program Files" / "Aerotech Updater",
        program_data_dir=data,
        config_path=data / "config" / "config.toml",
        updater_log=data / "logs" / "updater.log",
        temp_root=temp_root,
        unpacked_dir=temp_root / "unpacked",
        rollback_dir=temp_root / "rollback",
        public_desktop=root / "Public" / "Desktop",
    )


with tempfile.TemporaryDirectory() as temp:
    paths = paths_for(Path(temp))
    (paths.install_dir / "app").mkdir(parents=True)
    (paths.install_dir / "app" / "aerotech-docflow.exe").write_bytes(b"legacy")
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text("private config", encoding="utf-8")
    report = {
        "config_loaded": True,
        "overridden_by_environment": [],
        "effective_environment": {"DOCFLOW_VERSION": "1.2.0"},
    }
    with (
        patch("updater.setup.probe_version_command", return_value=None),
        patch("updater.setup.run_json_command", return_value=report),
        patch(
            "updater.setup.read_current_health",
            return_value={"status": "ok", "service": "aerotech-docflow", "version": "1.2.0"},
        ),
    ):
        version = _determine_legacy_version(paths)
    assert str(version.version) == "1.2.0"
    assert version.config_schema == 2

    with (
        patch("updater.setup.probe_version_command", return_value=None),
        patch("updater.setup.run_json_command", return_value=report),
        patch("updater.setup.read_current_health", return_value=None),
    ):
        try:
            _determine_legacy_version(paths)
        except UpdaterError as exc:
            assert exc.code == "LEGACY_VERSION_UNKNOWN"
        else:
            raise AssertionError("one legacy config value must not be treated as an unambiguous version")

    with (
        patch("updater.setup.probe_version_command", return_value=None),
        patch("updater.setup.run_json_command", return_value=report),
        patch(
            "updater.setup.read_current_health",
            return_value={"status": "ok", "service": "aerotech-docflow", "version": "1.1.0"},
        ),
    ):
        try:
            _determine_legacy_version(paths)
        except UpdaterError as exc:
            assert exc.code == "LEGACY_VERSION_UNKNOWN"
        else:
            raise AssertionError("conflicting legacy version sources must stop setup")

print("UPDATER SETUP UNIT TEST OK")
