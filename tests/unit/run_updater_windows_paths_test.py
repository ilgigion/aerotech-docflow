from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from updater.errors import UpdaterError
from updater.windows import UpdaterPaths, _system_drive_root


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

print("UPDATER WINDOWS PATHS UNIT TEST OK")
