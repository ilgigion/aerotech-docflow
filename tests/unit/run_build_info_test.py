from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from app import build_info
from app.build_info import get_application_version, read_package_version


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    version_file = root / "version.json"
    version_file.write_text(
        json.dumps({"version": "1.3.0", "config_schema": 2}),
        encoding="utf-8",
    )
    assert read_package_version(version_file) == "1.3.0"

    fake_executable = root / "app" / "aerotech-docflow.exe"
    fake_executable.parent.mkdir()
    with (
        patch.object(build_info.sys, "frozen", True, create=True),
        patch.object(build_info.sys, "executable", str(fake_executable)),
    ):
        assert get_application_version() == "1.3.0"

    version_file.write_text(
        json.dumps({"version": "1.3.0", "config_schema": 2, "extra": True}),
        encoding="utf-8",
    )
    try:
        read_package_version(version_file)
    except ValueError:
        pass
    else:
        raise AssertionError("extra version.json fields must be rejected")

with patch.dict(os.environ, {"DOCFLOW_VERSION": "2.0.0"}, clear=False):
    assert get_application_version() == "2.0.0"

print("BUILD INFO UNIT TEST OK")
