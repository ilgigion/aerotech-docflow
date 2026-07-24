from __future__ import annotations

from pathlib import Path
import stat
import tempfile
import zipfile

from updater.errors import UpdaterError
from updater.package import extract_package, validate_package
from tests.unit.updater_test_support import create_package


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    valid_zip = create_package(root, "1.3.0")
    package = validate_package(valid_zip)
    assert str(package.version.version) == "1.3.0"
    assert package.version.config_schema == 2
    destination = root / "unpacked"
    extract_package(package, destination)
    assert (destination / "app" / "aerotech-docflow.exe").read_bytes() == b"fake application"

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    bad_hash = create_package(root, "1.3.1", corrupt_hash=True)
    try:
        validate_package(bad_hash)
    except UpdaterError as exc:
        assert exc.code == "FILE_HASH_MISMATCH"
    else:
        raise AssertionError("corrupt manifest hash must be rejected")

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    extra = create_package(root, "1.3.2", extra_files={"config.toml": b"secret"})
    try:
        validate_package(extra)
    except UpdaterError as exc:
        assert exc.code in {"UNEXPECTED_PACKAGE_FILE", "UNSAFE_ARCHIVE_PATH"}
    else:
        raise AssertionError("config.toml must be rejected")

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    traversal = root / "aerotech-docflow-v1.3.3.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../outside.txt", b"escape")
    try:
        validate_package(traversal)
    except UpdaterError as exc:
        assert exc.code == "UNSAFE_ARCHIVE_PATH"
    else:
        raise AssertionError("path traversal must be rejected")

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    broken = root / "aerotech-docflow-v1.3.4.zip"
    broken.write_bytes(b"not a zip")
    try:
        validate_package(broken)
    except UpdaterError as exc:
        assert exc.code == "INVALID_ZIP"
    else:
        raise AssertionError("corrupt ZIP must be rejected")

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    duplicate = root / "aerotech-docflow-v1.3.5.zip"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("version.json", b"{}")
        archive.writestr("Version.json", b"{}")
    try:
        validate_package(duplicate)
    except UpdaterError as exc:
        assert exc.code == "DUPLICATE_ARCHIVE_PATH"
    else:
        raise AssertionError("case-insensitive duplicate must be rejected")

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    symlink_zip = root / "aerotech-docflow-v1.3.6.zip"
    link = zipfile.ZipInfo("app/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink_zip, "w") as archive:
        archive.writestr(link, "target")
    try:
        validate_package(symlink_zip)
    except UpdaterError as exc:
        assert exc.code == "UNSAFE_ARCHIVE_PATH"
    else:
        raise AssertionError("symbolic link must be rejected")

print("UPDATER PACKAGE UNIT TEST OK")
