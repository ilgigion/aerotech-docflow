from __future__ import annotations

from pathlib import Path
import tempfile

from updater.errors import UpdaterError
from updater.models import SemVer, VersionInfo
from updater.package import select_newest_package
from tests.unit.updater_test_support import create_package


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    create_package(root, "1.2.0")
    create_package(root, "1.3.0")
    create_package(root, "1.4.0", corrupt_hash=True)
    create_package(root, "1.3.5")
    rejected: list[tuple[str, str]] = []
    selected = select_newest_package(
        root,
        VersionInfo(SemVer.parse("1.2.0"), 2),
        report_invalid=lambda path, error: rejected.append((path.name, error.code)),
    )
    assert str(selected.version.version) == "1.3.5"
    assert ("aerotech-docflow-v1.4.0.zip", "FILE_HASH_MISMATCH") in rejected

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    create_package(root, "1.2.0")
    create_package(root, "1.1.9")
    try:
        select_newest_package(root, VersionInfo(SemVer.parse("1.2.0"), 2))
    except UpdaterError as exc:
        assert exc.code == "PACKAGE_NOT_FOUND"
    else:
        raise AssertionError("equal/older versions must not be selected")

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    create_package(root, "1.3.0", schema=3)
    rejected: list[str] = []
    try:
        select_newest_package(
            root,
            VersionInfo(SemVer.parse("1.2.0"), 2),
            report_invalid=lambda _path, error: rejected.append(error.code),
        )
    except UpdaterError as exc:
        assert exc.code == "CONFIG_SCHEMA_MISMATCH"
    else:
        raise AssertionError("incompatible config schema must not be selected")
    assert "CONFIG_SCHEMA_MISMATCH" in rejected

assert SemVer.parse("1.3.0-rc.1") < SemVer.parse("1.3.0")
assert SemVer.parse("1.10.0") > SemVer.parse("1.9.9")

print("UPDATER SELECTION UNIT TEST OK")
