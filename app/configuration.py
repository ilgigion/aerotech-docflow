from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import tomllib
from typing import Any, MutableMapping


class ConfigurationFileError(RuntimeError):
    """Raised when a machine configuration file is invalid or unsafe to use."""


@dataclass(frozen=True)
class AppliedConfiguration:
    path: Path | None
    loaded: bool
    applied_environment: dict[str, str]
    overridden_by_environment: tuple[str, ...]


CONFIG_ENV_VAR = "DOCFLOW_CONFIG_FILE"
DEFAULT_CONFIG_DIRECTORY_NAME = "Aerotech Docflow"
DEFAULT_CONFIG_FILE_NAME = "config.toml"


# TOML path -> environment variable. The application continues to consume its
# established environment contract, so configuration files do not create a
# second independent settings implementation.
CONFIG_KEYS: dict[tuple[str, ...], str] = {
    ("application", "environment"): "DOCFLOW_ENV",
    ("application", "version"): "DOCFLOW_VERSION",
    ("application", "host"): "DOCFLOW_HOST",
    ("application", "port"): "DOCFLOW_PORT",
    ("scanner", "naps2_executable"): "NAPS2_EXECUTABLE",
    ("scanner", "profile"): "NAPS2_PROFILE",
    ("scanner", "output_encoding"): "NAPS2_OUTPUT_ENCODING",
    ("scanner", "incoming_dir"): "SCANNER_INCOMING_DIR",
    ("scanner", "timeout_seconds"): "SCANNER_TIMEOUT_SECONDS",
    ("scanner", "timeout_kill_grace_seconds"): "SCANNER_TIMEOUT_KILL_GRACE_SECONDS",
    ("scanner", "verify_process_exit_seconds"): "SCANNER_VERIFY_PROCESS_EXIT_SECONDS",
    ("scanner", "quarantine_failed_outputs"): "SCANNER_QUARANTINE_FAILED_OUTPUTS",
    ("scanner", "failed_scan_dir_name"): "SCANNER_FAILED_SCAN_DIR_NAME",
    ("scanner", "min_pdf_size_bytes"): "SCANNER_MIN_PDF_SIZE_BYTES",
    ("scanner", "min_pdf_pages"): "SCANNER_MIN_PDF_PAGES",
    ("scanner", "stable_checks"): "SCANNER_STABLE_CHECKS",
    ("scanner", "stable_interval_seconds"): "SCANNER_STABLE_INTERVAL_SECONDS",
    ("scanner", "direct", "driver"): "SCANNER_DRIVER",
    ("scanner", "direct", "device_name"): "SCANNER_DEVICE_NAME",
    ("scanner", "direct", "source"): "SCANNER_SOURCE",
    ("scanner", "direct", "dpi"): "SCANNER_DPI",
    ("scanner", "direct", "page_size"): "SCANNER_PAGE_SIZE",
    ("scanner", "direct", "bit_depth"): "SCANNER_BIT_DEPTH",
    ("archive", "root"): "ARCHIVE_ROOT",
    ("archive", "confirmation"): "DOCFLOW_ARCHIVE_CONFIRMATION",
    ("archive", "archive_id"): "DOCFLOW_ARCHIVE_ID",
    ("archive", "allowed_doc_types"): "DOCFLOW_ALLOWED_DOC_TYPES",
    ("archive", "min_document_year"): "DOCFLOW_MIN_DOCUMENT_YEAR",
    ("archive", "max_document_year"): "DOCFLOW_MAX_DOCUMENT_YEAR",
    ("storage", "copy_buffer_size"): "STORAGE_COPY_BUFFER_SIZE",
    ("storage", "keep_temp_on_error"): "STORAGE_KEEP_TEMP_ON_ERROR",
    ("storage", "reservation_stale_seconds"): "STORAGE_RESERVATION_STALE_AFTER_SECONDS",
    ("locking", "stale_seconds"): "SCANNER_LOCK_STALE_SECONDS",
    ("locking", "wait_timeout_seconds"): "SCANNER_LOCK_WAIT_TIMEOUT_SECONDS",
    ("locking", "retry_interval_seconds"): "SCANNER_LOCK_RETRY_INTERVAL_SECONDS",
    ("locking", "allow_stale_takeover"): "SCANNER_LOCK_ALLOW_STALE_TAKEOVER",
    ("logging", "enabled"): "DOCFLOW_MONTHLY_FILE_LOGS",
    ("logging", "level"): "DOCFLOW_LOG_LEVEL",
    ("logging", "directory"): "DOCFLOW_LOG_DIR",
    ("logging", "max_bytes"): "DOCFLOW_LOG_MAX_BYTES",
    ("logging", "backup_count"): "DOCFLOW_LOG_BACKUP_COUNT",
    ("logging", "retention_months"): "DOCFLOW_LOG_RETENTION_MONTHS",
    ("idempotency", "enabled"): "DOCFLOW_IDEMPOTENCY_ENABLED",
    ("idempotency", "directory"): "DOCFLOW_IDEMPOTENCY_DIR",
    ("idempotency", "stale_seconds"): "DOCFLOW_IDEMPOTENCY_STALE_SECONDS",
    ("cleanup", "quarantine_dir_name"): "INCOMING_CLEANUP_QUARANTINE_DIR_NAME",
    ("cleanup", "managed_prefix"): "INCOMING_CLEANUP_MANAGED_PREFIX",
    ("cleanup", "managed_suffix"): "INCOMING_CLEANUP_MANAGED_SUFFIX",
    ("cleanup", "min_age_seconds"): "INCOMING_CLEANUP_MIN_AGE_SECONDS",
    ("cleanup", "skip_if_lock_exists"): "INCOMING_CLEANUP_SKIP_IF_LOCK_EXISTS",
    ("cleanup", "stable_checks"): "INCOMING_CLEANUP_STABLE_CHECKS",
    ("cleanup", "stable_interval_seconds"): "INCOMING_CLEANUP_STABLE_INTERVAL_SECONDS",
}


def default_config_path() -> Path:
    program_data = os.getenv("PROGRAMDATA", "").strip()
    if not program_data:
        raise ConfigurationFileError(
            "PROGRAMDATA is empty; pass --config or set DOCFLOW_CONFIG_FILE"
        )
    return (
        Path(program_data)
        / DEFAULT_CONFIG_DIRECTORY_NAME
        / "config"
        / DEFAULT_CONFIG_FILE_NAME
    )


def resolve_config_path(explicit: Path | str | None = None) -> tuple[Path, bool]:
    """Return path and whether its existence was explicitly requested."""

    if explicit is not None:
        return Path(explicit).expanduser().resolve(strict=False), True
    from_environment = os.getenv(CONFIG_ENV_VAR, "").strip()
    if from_environment:
        return Path(from_environment).expanduser().resolve(strict=False), True
    return default_config_path().resolve(strict=False), False


def _flatten(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    flattened: dict[tuple[str, ...], Any] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ConfigurationFileError("TOML configuration keys must be strings")
        path = (*prefix, key)
        if isinstance(value, dict):
            flattened.update(_flatten(value, path))
        else:
            flattened[path] = value
    return flattened


def _to_environment_value(key: tuple[str, ...], value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigurationFileError(
                f"Configuration value must be finite: {'.'.join(key)}"
            )
        return str(value)
    if isinstance(value, str):
        if "\x00" in value:
            raise ConfigurationFileError(f"Configuration value contains NUL: {'.'.join(key)}")
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if any("," in item for item in value):
            raise ConfigurationFileError(
                f"List values must not contain commas: {'.'.join(key)}"
            )
        return ",".join(value)
    raise ConfigurationFileError(
        f"Unsupported value type for {'.'.join(key)}: {type(value).__name__}"
    )


def load_config_environment(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigurationFileError(f"Cannot read configuration file: {path}") from exc
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationFileError(f"Invalid UTF-8 TOML configuration: {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigurationFileError(f"TOML root must be a table: {path}")

    flattened = _flatten(parsed)
    unknown = sorted(".".join(key) for key in flattened if key not in CONFIG_KEYS)
    if unknown:
        raise ConfigurationFileError(
            "Unknown configuration keys: " + ", ".join(unknown)
        )

    result: dict[str, str] = {}
    for key, value in flattened.items():
        result[CONFIG_KEYS[key]] = _to_environment_value(key, value)
    return result


def apply_configuration(
    explicit_path: Path | str | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> AppliedConfiguration:
    target = os.environ if environ is None else environ
    path, required = resolve_config_path(explicit_path)
    if not path.exists():
        if required:
            raise ConfigurationFileError(f"Configuration file does not exist: {path}")
        return AppliedConfiguration(path=path, loaded=False, applied_environment={}, overridden_by_environment=())
    if not path.is_file():
        raise ConfigurationFileError(f"Configuration path is not a file: {path}")

    values = load_config_environment(path)
    applied: dict[str, str] = {}
    overridden: list[str] = []
    for name, value in values.items():
        if name in target:
            overridden.append(name)
            continue
        target[name] = value
        applied[name] = value
    if explicit_path is not None:
        target[CONFIG_ENV_VAR] = str(path)
    else:
        target.setdefault(CONFIG_ENV_VAR, str(path))
    return AppliedConfiguration(
        path=path,
        loaded=True,
        applied_environment=applied,
        overridden_by_environment=tuple(sorted(overridden)),
    )


def effective_environment_snapshot() -> dict[str, str | None]:
    names = sorted(set(CONFIG_KEYS.values()) | {CONFIG_ENV_VAR})
    return {name: os.getenv(name) for name in names}


def effective_environment_json() -> str:
    return json.dumps(effective_environment_snapshot(), ensure_ascii=False, indent=2)
