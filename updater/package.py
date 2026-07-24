from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from typing import Callable
import zipfile

from updater.errors import UpdaterError
from updater.models import ManifestEntry, SemVer, ValidatedPackage, VersionInfo


MAX_ZIP_BYTES = 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 100_000
MAX_METADATA_BYTES = 1024 * 1024
_PACKAGE_NAME_RE = re.compile(r"^aerotech-docflow-v(.+)\.zip$", re.IGNORECASE)
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _safe_archive_path(value: str, *, allow_directory: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise UpdaterError("UNSAFE_ARCHIVE_PATH", "ZIP содержит пустой путь.")
    if "\\" in value or value.startswith("/") or value.endswith("/") and not allow_directory:
        raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Недопустимый путь в ZIP: {value!r}")
    normalized = value[:-1] if allow_directory and value.endswith("/") else value
    if not normalized:
        raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Недопустимый путь в ZIP: {value!r}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or len(path.parts) == 0:
        raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Абсолютный путь в ZIP: {value!r}")
    for part in path.parts:
        if part in {"", ".", ".."} or ":" in part or part.endswith((".", " ")):
            raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Опасный сегмент пути в ZIP: {value!r}")
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED:
            raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Зарезервированное имя Windows: {value!r}")
    if path.parts[0].casefold() not in {"app", "service", "version.json", "build-manifest.json"}:
        raise UpdaterError("UNEXPECTED_PACKAGE_FILE", f"Лишний верхний путь в ZIP: {value!r}")
    if len(path.parts) > 1 and path.parts[0].casefold() in {"version.json", "build-manifest.json"}:
        raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Некорректный путь метаданных: {value!r}")
    return "/".join(path.parts)


def _json_from_zip(archive: zipfile.ZipFile, name: str) -> object:
    info = archive.getinfo(name)
    if info.file_size > MAX_METADATA_BYTES:
        raise UpdaterError("INVALID_PACKAGE_METADATA", f"Слишком большой файл метаданных: {name}")
    try:
        return json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, OSError) as exc:
        raise UpdaterError("INVALID_PACKAGE_METADATA", f"Не удалось прочитать {name}: {exc}") from exc


def _sha256_zip_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info, "r") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package(zip_path: Path) -> ValidatedPackage:
    zip_path = zip_path.resolve(strict=True)
    if not zip_path.is_file() or zip_path.stat().st_size == 0:
        raise UpdaterError("INVALID_ZIP", f"ZIP отсутствует или пуст: {zip_path}")
    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        raise UpdaterError("INVALID_ZIP", f"ZIP превышает лимит 1 GiB: {zip_path}")
    match = _PACKAGE_NAME_RE.fullmatch(zip_path.name)
    if not match:
        raise UpdaterError("INVALID_PACKAGE_NAME", f"Некорректное имя ZIP: {zip_path.name}")
    filename_version = SemVer.parse(match.group(1))

    try:
        archive = zipfile.ZipFile(zip_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdaterError("INVALID_ZIP", f"Повреждённый ZIP: {zip_path.name}") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ENTRIES:
            raise UpdaterError("INVALID_ZIP", "Некорректное количество элементов ZIP.")
        files: dict[str, zipfile.ZipInfo] = {}
        directories: set[str] = set()
        seen: set[str] = set()
        expanded = 0
        for info in infos:
            is_directory = info.is_dir()
            safe_name = _safe_archive_path(info.filename, allow_directory=is_directory)
            key = safe_name.casefold()
            if key in seen:
                raise UpdaterError("DUPLICATE_ARCHIVE_PATH", f"Дублирующийся путь ZIP: {safe_name}")
            seen.add(key)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode) or (info.external_attr & 0x400):
                raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Ссылка/reparse point запрещена: {safe_name}")
            if info.flag_bits & 0x1:
                raise UpdaterError("INVALID_ZIP", f"Зашифрованные элементы ZIP запрещены: {safe_name}")
            if is_directory:
                directories.add(safe_name)
                continue
            expanded += info.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise UpdaterError("INVALID_ZIP", "Распакованный пакет превышает лимит 2 GiB.")
            files[safe_name] = info

        for directory in directories:
            prefix = directory + "/"
            if not any(path.startswith(prefix) for path in files):
                raise UpdaterError(
                    "UNEXPECTED_PACKAGE_FILE",
                    f"ZIP содержит лишний пустой каталог: {directory}",
                )

        required = {
            "app/aerotech-docflow.exe",
            "service/docflow-service.exe",
            "service/docflow-service.xml.template",
            "version.json",
            "build-manifest.json",
        }
        missing = sorted(path for path in required if path not in files)
        if missing:
            raise UpdaterError("PACKAGE_FILE_MISSING", f"В ZIP отсутствуют файлы: {', '.join(missing)}")

        version = VersionInfo.from_json(_json_from_zip(archive, "version.json"))
        if version.version != filename_version or str(version.version) != str(filename_version):
            raise UpdaterError(
                "PACKAGE_VERSION_MISMATCH",
                f"Версия ZIP {filename_version} не совпадает с version.json {version.version}.",
            )
        manifest_payload = _json_from_zip(archive, "build-manifest.json")
        if not isinstance(manifest_payload, list) or not manifest_payload:
            raise UpdaterError("INVALID_MANIFEST", "build-manifest.json должен быть непустым массивом.")
        manifest = tuple(ManifestEntry.from_json(item) for item in manifest_payload)
        manifest_by_path: dict[str, ManifestEntry] = {}
        manifest_keys: set[str] = set()
        previous_path = ""
        for entry in manifest:
            safe_path = _safe_archive_path(entry.path)
            if safe_path != entry.path:
                raise UpdaterError("INVALID_MANIFEST", f"Путь manifest не нормализован: {entry.path}")
            key = safe_path.casefold()
            if key in manifest_keys:
                raise UpdaterError("INVALID_MANIFEST", f"Дублирующийся путь manifest: {safe_path}")
            if safe_path == "build-manifest.json":
                raise UpdaterError("INVALID_MANIFEST", "Manifest не должен включать сам себя.")
            if previous_path and safe_path <= previous_path:
                raise UpdaterError("INVALID_MANIFEST", "Записи manifest должны быть отсортированы по path.")
            previous_path = safe_path
            manifest_keys.add(key)
            manifest_by_path[safe_path] = entry

        actual_manifest_files = set(files) - {"build-manifest.json"}
        if set(manifest_by_path) != actual_manifest_files:
            missing_manifest = sorted(actual_manifest_files - set(manifest_by_path))
            extra_manifest = sorted(set(manifest_by_path) - actual_manifest_files)
            raise UpdaterError(
                "MANIFEST_FILE_SET_MISMATCH",
                f"Manifest не совпадает с ZIP; не описаны={missing_manifest}, отсутствуют={extra_manifest}",
            )
        for path, entry in manifest_by_path.items():
            info = files[path]
            if info.file_size != entry.size:
                raise UpdaterError("FILE_SIZE_MISMATCH", f"Размер не совпадает с manifest: {path}")
            if _sha256_zip_entry(archive, info) != entry.sha256:
                raise UpdaterError("FILE_HASH_MISMATCH", f"SHA-256 не совпадает с manifest: {path}")

    return ValidatedPackage(zip_path=zip_path, version=version, manifest=manifest)


def select_newest_package(
    temp_root: Path,
    installed: VersionInfo,
    *,
    report_invalid: Callable[[Path, UpdaterError], None] | None = None,
) -> ValidatedPackage:
    candidates: list[ValidatedPackage] = []
    schema_errors: list[UpdaterError] = []
    if not temp_root.is_dir():
        raise UpdaterError("PACKAGE_NOT_FOUND", f"Каталог пакетов не найден: {temp_root}")
    for path in sorted(temp_root.glob("*.zip"), key=lambda item: item.name.casefold()):
        if not _PACKAGE_NAME_RE.fullmatch(path.name):
            continue
        try:
            package = validate_package(path)
            if package.version.version <= installed.version:
                continue
            if package.version.config_schema != installed.config_schema:
                raise UpdaterError(
                    "CONFIG_SCHEMA_MISMATCH",
                    f"Пакет {package.version.version}: config_schema="
                    f"{package.version.config_schema}, установлено={installed.config_schema}.",
                )
            candidates.append(package)
        except UpdaterError as exc:
            if exc.code == "CONFIG_SCHEMA_MISMATCH":
                schema_errors.append(exc)
            if report_invalid is not None:
                report_invalid(path, exc)
    if not candidates:
        if schema_errors:
            raise schema_errors[-1]
        raise UpdaterError(
            "PACKAGE_NOT_FOUND",
            f"Новый корректный пакет обновления не найден в: {temp_root}",
        )
    return max(candidates, key=lambda package: package.version.version)


def extract_package(package: ValidatedPackage, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve(strict=True)
    root_prefix = os.path.normcase(str(root) + os.sep)
    try:
        with zipfile.ZipFile(Path(package.zip_path), "r") as archive:
            for info in archive.infolist():
                safe_name = _safe_archive_path(info.filename, allow_directory=info.is_dir())
                output = (root / Path(*PurePosixPath(safe_name).parts)).resolve(strict=False)
                normalized_output = os.path.normcase(str(output))
                if normalized_output != os.path.normcase(str(root)) and not normalized_output.startswith(root_prefix):
                    raise UpdaterError("UNSAFE_ARCHIVE_PATH", f"Путь выходит из unpacked: {safe_name}")
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, output.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
