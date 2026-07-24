from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


BASE_FILES = {
    "app/aerotech-docflow.exe": b"fake application",
    "service/docflow-service.exe": b"fake winsw",
    "service/docflow-service.xml.template": (
        b"<service><executable>__DOCFLOW_EXE__</executable>"
        b"<arguments>--config __CONFIG_PATH__ run</arguments>"
        b"<workingdirectory>__APP_DIR__</workingdirectory>"
        b"<logpath>__SERVICE_LOG_DIR__</logpath>__SERVICE_ACCOUNT__</service>"
    ),
}


def create_package(
    root: Path,
    version: str,
    *,
    schema: int = 2,
    extra_files: dict[str, bytes] | None = None,
    corrupt_hash: bool = False,
) -> Path:
    files = dict(BASE_FILES)
    files.update(extra_files or {})
    files["version.json"] = (
        json.dumps({"version": version, "config_schema": schema}, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manifest = []
    for path in sorted(files):
        digest = hashlib.sha256(files[path]).hexdigest()
        if corrupt_hash and path == "app/aerotech-docflow.exe":
            digest = "0" * 64
        manifest.append({"path": path, "size": len(files[path]), "sha256": digest})
    files["build-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    target = root / f"aerotech-docflow-v{version}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return target

