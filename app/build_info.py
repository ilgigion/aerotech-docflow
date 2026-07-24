from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def installed_version_file() -> Path | None:
    """Return the package-level version.json for a frozen onedir build."""

    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve(strict=False)
    return executable.parent.parent / "version.json"


def read_package_version(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read package version file: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != {"version", "config_schema"}:
        raise ValueError(f"Invalid package version file structure: {path}")
    version = payload.get("version")
    schema = payload.get("config_schema")
    if not isinstance(version, str) or not _SEMVER_RE.fullmatch(version):
        raise ValueError(f"Invalid package version in: {path}")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
        raise ValueError(f"Invalid config_schema in: {path}")
    return version


def get_application_version() -> str:
    """Use immutable release metadata in production and env in development."""

    version_file = installed_version_file()
    if version_file is not None:
        return read_package_version(version_file)
    return os.getenv("DOCFLOW_VERSION", "dev").strip() or "dev"
