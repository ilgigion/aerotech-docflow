from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import os

from app.naming import normalize_doc_type


PRODUCTION_ENV_NAMES = {"prod", "production"}
ARCHIVE_MARKER_NAME = ".aerotech-docflow-archive.json"
ARCHIVE_MARKER_VALUE = "aerotech-docflow-archive-v1"


class ProductionConfigurationError(RuntimeError):
    """Raised when production safety invariants are not explicitly configured."""


@dataclass(frozen=True)
class RuntimeSafetyConfig:
    environment: str
    production: bool
    archive_root: Path
    incoming_dir: Path
    allowed_doc_types: frozenset[str]
    min_document_year: int | None
    max_document_year: int | None


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ProductionConfigurationError(
            f"Production variable {name} must be set explicitly"
        )
    return value


def _parse_optional_year(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        year = int(raw)
    except ValueError as exc:
        raise ProductionConfigurationError(f"{name} must be an integer") from exc
    if year < 1900 or year > 9999:
        raise ProductionConfigurationError(f"{name} is outside 1900..9999")
    return year


def load_runtime_safety_config() -> RuntimeSafetyConfig:
    environment = os.getenv("DOCFLOW_ENV", "development").strip().lower()
    production = environment in PRODUCTION_ENV_NAMES

    archive_value = (
        _required_env("ARCHIVE_ROOT")
        if production
        else os.getenv("ARCHIVE_ROOT", r"D:\archive_test")
    )
    incoming_value = (
        _required_env("SCANNER_INCOMING_DIR")
        if production
        else os.getenv("SCANNER_INCOMING_DIR", r"D:\incoming")
    )

    raw_allowed_types = os.getenv("DOCFLOW_ALLOWED_DOC_TYPES", "")
    canonical_types: set[str] = set()
    for item in raw_allowed_types.split(","):
        value = item.strip()
        if not value:
            continue
        normalized = normalize_doc_type(value)
        if normalized != value:
            raise ProductionConfigurationError(
                "DOCFLOW_ALLOWED_DOC_TYPES values must already be canonical uppercase file-safe names"
            )
        canonical_types.add(normalized)
    allowed_types = frozenset(canonical_types)

    return RuntimeSafetyConfig(
        environment=environment,
        production=production,
        archive_root=Path(archive_value),
        incoming_dir=Path(incoming_value),
        allowed_doc_types=allowed_types,
        min_document_year=_parse_optional_year("DOCFLOW_MIN_DOCUMENT_YEAR"),
        max_document_year=_parse_optional_year("DOCFLOW_MAX_DOCUMENT_YEAR"),
    )


def validate_document_business_rules(*, doc_type: str, document_datetime: datetime) -> None:
    config = load_runtime_safety_config()
    normalized_type = normalize_doc_type(doc_type)

    if config.allowed_doc_types and normalized_type not in config.allowed_doc_types:
        raise ValueError(f"doc_type is not allowed: {normalized_type}")

    if config.min_document_year is not None and document_datetime.year < config.min_document_year:
        raise ValueError(
            f"document_datetime year is earlier than {config.min_document_year}"
        )
    if config.max_document_year is not None and document_datetime.year > config.max_document_year:
        raise ValueError(
            f"document_datetime year is later than {config.max_document_year}"
        )


def validate_runtime_environment() -> RuntimeSafetyConfig:
    """Validate configuration without starting NAPS2 or writing to the archive."""

    config = load_runtime_safety_config()
    if not config.production:
        return config

    archive_root = config.archive_root.resolve(strict=False)
    incoming_dir = config.incoming_dir.resolve(strict=False)
    version = _required_env("DOCFLOW_VERSION")
    if version.lower() in {"dev", "development", "unknown"}:
        raise ProductionConfigurationError("DOCFLOW_VERSION must identify the production build")
    naps2_executable = Path(_required_env("NAPS2_EXECUTABLE"))
    log_dir = Path(_required_env("DOCFLOW_LOG_DIR")).resolve(strict=False)
    idempotency_dir = Path(_required_env("DOCFLOW_IDEMPOTENCY_DIR")).resolve(strict=False)

    if not config.archive_root.exists() or not config.archive_root.is_dir():
        raise ProductionConfigurationError(
            f"Production archive root must already exist and be a directory: {config.archive_root}"
        )
    if not config.incoming_dir.exists() or not config.incoming_dir.is_dir():
        raise ProductionConfigurationError(
            f"Production incoming directory must already exist: {config.incoming_dir}"
        )
    if not naps2_executable.exists() or not naps2_executable.is_file():
        raise ProductionConfigurationError(
            f"NAPS2_EXECUTABLE must point to an existing file: {naps2_executable}"
        )
    profile = os.getenv("NAPS2_PROFILE", "").strip()
    if not profile:
        _required_env("SCANNER_DRIVER")
        _required_env("SCANNER_DEVICE_NAME")
    for name, path in {
        "DOCFLOW_LOG_DIR": log_dir,
        "DOCFLOW_IDEMPOTENCY_DIR": idempotency_dir,
    }.items():
        if not path.exists() or not path.is_dir():
            raise ProductionConfigurationError(
                f"{name} must already exist and be a directory: {path}"
            )
        if path == archive_root or archive_root in path.parents:
            raise ProductionConfigurationError(f"{name} must be outside ARCHIVE_ROOT")
    if any(part.lower() == "archive_test" for part in archive_root.parts):
        raise ProductionConfigurationError(
            f"Test archive path is forbidden in production: {archive_root}"
        )
    if archive_root == incoming_dir or archive_root in incoming_dir.parents or incoming_dir in archive_root.parents:
        raise ProductionConfigurationError(
            "ARCHIVE_ROOT and SCANNER_INCOMING_DIR must be separate, non-nested directories"
        )

    confirmation = Path(_required_env("DOCFLOW_ARCHIVE_CONFIRMATION")).resolve(strict=False)
    if confirmation != archive_root:
        raise ProductionConfigurationError(
            "DOCFLOW_ARCHIVE_CONFIRMATION must exactly match resolved ARCHIVE_ROOT"
        )

    archive_id = _required_env("DOCFLOW_ARCHIVE_ID")
    marker_path = config.archive_root / ARCHIVE_MARKER_NAME
    try:
        marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProductionConfigurationError(
            f"Production archive marker is missing or invalid: {marker_path}"
        ) from exc
    if not isinstance(marker_data, dict) or (
        marker_data.get("marker") != ARCHIVE_MARKER_VALUE
        or marker_data.get("archive_id") != archive_id
    ):
        raise ProductionConfigurationError(
            f"Production archive marker identity mismatch: {marker_path}"
        )

    if not config.allowed_doc_types:
        raise ProductionConfigurationError(
            "DOCFLOW_ALLOWED_DOC_TYPES must contain at least one production document type"
        )
    if config.min_document_year is None or config.max_document_year is None:
        raise ProductionConfigurationError(
            "DOCFLOW_MIN_DOCUMENT_YEAR and DOCFLOW_MAX_DOCUMENT_YEAR are required in production"
        )
    if config.min_document_year > config.max_document_year:
        raise ProductionConfigurationError(
            "DOCFLOW_MIN_DOCUMENT_YEAR must not exceed DOCFLOW_MAX_DOCUMENT_YEAR"
        )

    if not _env_flag("DOCFLOW_IDEMPOTENCY_ENABLED", True):
        raise ProductionConfigurationError("Idempotency cannot be disabled in production")
    if not _env_flag("DOCFLOW_MONTHLY_FILE_LOGS", True):
        raise ProductionConfigurationError("File logging cannot be disabled in production")

    try:
        scanner_timeout = int(os.getenv("SCANNER_TIMEOUT_SECONDS", "180"))
        kill_grace = int(os.getenv("SCANNER_TIMEOUT_KILL_GRACE_SECONDS", "10"))
        verify_exit = int(os.getenv("SCANNER_VERIFY_PROCESS_EXIT_SECONDS", "5"))
        idempotency_stale = int(os.getenv("DOCFLOW_IDEMPOTENCY_STALE_SECONDS", "1800"))
        reservation_stale = int(os.getenv("STORAGE_RESERVATION_STALE_AFTER_SECONDS", "1800"))
        copy_buffer = int(os.getenv("STORAGE_COPY_BUFFER_SIZE", str(1024 * 1024)))
        log_max_bytes = int(_required_env("DOCFLOW_LOG_MAX_BYTES"))
        log_backup_count = int(_required_env("DOCFLOW_LOG_BACKUP_COUNT"))
        log_retention_months = int(_required_env("DOCFLOW_LOG_RETENTION_MONTHS"))
    except ValueError as exc:
        raise ProductionConfigurationError(
            "Production timeout and stale settings must be integers"
        ) from exc

    minimum_stale = scanner_timeout + kill_grace + verify_exit + 60
    if idempotency_stale < minimum_stale:
        raise ProductionConfigurationError(
            f"DOCFLOW_IDEMPOTENCY_STALE_SECONDS must be at least {minimum_stale}"
        )
    if reservation_stale < minimum_stale:
        raise ProductionConfigurationError(
            f"STORAGE_RESERVATION_STALE_AFTER_SECONDS must be at least {minimum_stale}"
        )
    if copy_buffer <= 0:
        raise ProductionConfigurationError("STORAGE_COPY_BUFFER_SIZE must be positive")
    if log_max_bytes <= 0 or log_backup_count < 1 or log_retention_months < 1:
        raise ProductionConfigurationError(
            "Production log size, backup count and retention must be positive"
        )

    return config
