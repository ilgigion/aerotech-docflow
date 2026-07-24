from __future__ import annotations

import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from updater.errors import UpdaterError
from updater.windows import UpdaterPaths, _system_drive_root, start_service


assert _system_drive_root("C:") == Path("C:\\")
assert _system_drive_root("d:\\") == Path("D:\\")

for unsafe in ("", "C:Temp", "Temp", r"\\server\\share"):
    try:
        _system_drive_root(unsafe)
    except UpdaterError as exc:
        assert exc.code == "PATH_RESOLUTION_FAILED"
    else:
        raise AssertionError(f"unsafe SystemDrive must be rejected: {unsafe!r}")

environment = {
    "ProgramW6432": r"C:\Program Files",
    "ProgramData": r"C:\ProgramData",
    "SystemDrive": "C:",
    "PUBLIC": r"C:\Users\Public",
}
with (
    patch.dict(os.environ, environment, clear=False),
    patch("updater.windows._is_64bit_windows", return_value=True),
):
    paths = UpdaterPaths.production()
assert paths.temp_root == Path(r"C:\Temp\Aerotech Docflow")
assert paths.temp_root.is_absolute()
assert str(paths.temp_root).startswith("C:\\Temp\\")

messages: list[str] = []
with (
    patch("updater.windows.service_state", return_value=1),
    patch(
        "updater.windows._run",
        return_value=subprocess.CompletedProcess(
            args=["sc.exe"],
            returncode=5,
            stdout="service output",
            stderr="access denied",
        ),
    ),
):
    try:
        start_service(report=messages.append)
    except UpdaterError as exc:
        assert exc.code == "SERVICE_START_FAILED"
        assert "exit=5" in exc.message
        assert "access denied" in exc.message
    else:
        raise AssertionError("non-zero sc.exe result must fail with diagnostics")
assert any("exit=5" in message for message in messages)

print("UPDATER WINDOWS PATHS UNIT TEST OK")
