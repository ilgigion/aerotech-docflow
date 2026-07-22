from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import hashlib
import json
import logging
import os
import re
import secrets
import socket
import time

from app.naming import normalize_doc_type, normalize_document_number, parse_document_datetime
from app.locks import is_process_running


logger = logging.getLogger(__name__)

IdempotencyStatus = Literal[
    "processing",
    "scanned",
    "storing",
    "succeeded",
    "failed",
    "interrupted",
    "timeout",
]

IdempotencyDecisionMode = Literal[
    "disabled",
    "run_new_scan",
    "return_existing",
    "retry_storage",
]

VALID_IDEMPOTENCY_STATUSES = {
    "processing",
    "scanned",
    "storing",
    "succeeded",
    "failed",
    "interrupted",
    "timeout",
}


class IdempotencyError(RuntimeError):
    def __init__(
        self,
        code: str,
        operator_message: str,
        technical_message: str = "",
        *,
        idempotency_key: str | None = None,
        record_path: Path | None = None,
        record: dict[str, Any] | None = None,
    ):
        super().__init__(operator_message)
        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message
        self.idempotency_key = idempotency_key
        self.record_path = record_path
        self.record = record or {}

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "idempotency_key": self.idempotency_key,
            "record_path": str(self.record_path) if self.record_path else None,
            "record": self.record,
        }


class IdempotencyInProgressError(IdempotencyError):
    pass


class IdempotencyRecordError(IdempotencyError):
    pass


class IdempotencyConflictError(IdempotencyError):
    pass


@dataclass(frozen=True)
class IdempotencySettings:
    """
    Файловая идемпотентность без SQLite.

    record_dir:
        Папка для JSON-маркеров операций. Задаётся в config.toml.

    in_progress_stale_after_seconds:
        Через сколько секунд незавершённую processing/storing запись можно
        считать старой. Это не удаляет PDF и не трогает сканер, а только
        разрешает новую попытку с тем же idempotency_key.

    enabled:
        Если False, idempotency_key игнорируется.
    """

    record_dir: Path | None = None
    in_progress_stale_after_seconds: int = 30 * 60
    enabled: bool = True


@dataclass(frozen=True)
class IdempotencyRecord:
    idempotency_key: str
    status: IdempotencyStatus
    operation_id: str
    task_id: str
    doc_type: str
    document_datetime: str
    document_number: str
    expected_file_name: str
    request_fingerprint: str = ""
    temp_scan_path: str | None = None
    final_file_name: str | None = None
    final_file_path: str | None = None
    error_code: str | None = None
    operator_message: str | None = None
    technical_message: str | None = None
    attempt: int = 1
    pid: int = os.getpid()
    hostname: str = socket.gethostname()
    created_at_utc: str = ""
    updated_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        now = utc_now_iso()
        return {
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "doc_type": self.doc_type,
            "document_datetime": self.document_datetime,
            "document_number": self.document_number,
            "expected_file_name": self.expected_file_name,
            "request_fingerprint": self.request_fingerprint,
            "temp_scan_path": self.temp_scan_path,
            "final_file_name": self.final_file_name,
            "final_file_path": self.final_file_path,
            "error_code": self.error_code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
            "attempt": self.attempt,
            "pid": self.pid,
            "hostname": self.hostname,
            "created_at_utc": self.created_at_utc or now,
            "updated_at_utc": self.updated_at_utc or now,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IdempotencyRecord":
        raw_status = str(data.get("status", "failed"))
        if raw_status not in VALID_IDEMPOTENCY_STATUSES:
            raise ValueError(f"Unknown idempotency status: {raw_status!r}")
        return cls(
            idempotency_key=str(data.get("idempotency_key", "")),
            status=raw_status,  # type: ignore[arg-type]
            operation_id=str(data.get("operation_id", "")),
            task_id=str(data.get("task_id", "")),
            doc_type=str(data.get("doc_type", "")),
            document_datetime=str(data.get("document_datetime", "")),
            document_number=str(data.get("document_number", "")),
            expected_file_name=str(data.get("expected_file_name", "")),
            request_fingerprint=str(data.get("request_fingerprint", "")),
            temp_scan_path=_optional_str(data.get("temp_scan_path")),
            final_file_name=_optional_str(data.get("final_file_name")),
            final_file_path=_optional_str(data.get("final_file_path")),
            error_code=_optional_str(data.get("error_code")),
            operator_message=_optional_str(data.get("operator_message")),
            technical_message=_optional_str(data.get("technical_message")),
            attempt=int(data.get("attempt", 1) or 1),
            pid=int(data.get("pid", os.getpid()) or os.getpid()),
            hostname=str(data.get("hostname", socket.gethostname())),
            created_at_utc=str(data.get("created_at_utc", "")),
            updated_at_utc=str(data.get("updated_at_utc", "")),
        )


@dataclass(frozen=True)
class IdempotencyDecision:
    mode: IdempotencyDecisionMode
    record: IdempotencyRecord | None = None
    record_path: Path | None = None
    reason: str = ""



def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None



def utc_now() -> datetime:
    return datetime.now(timezone.utc)



def utc_now_iso() -> str:
    return utc_now().isoformat()



def parse_datetime_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None



def load_idempotency_settings_from_env(default_incoming_dir: Path | str | None = None) -> IdempotencySettings:
    configured_dir = os.getenv("DOCFLOW_IDEMPOTENCY_DIR", "").strip()
    if configured_dir:
        record_dir = Path(configured_dir)
    elif default_incoming_dir is not None:
        record_dir = Path(default_incoming_dir) / "_idempotency"
    else:
        raise ValueError(
            "DOCFLOW_IDEMPOTENCY_DIR is empty; set idempotency.directory in config.toml"
        )
    return IdempotencySettings(
        record_dir=record_dir,
        in_progress_stale_after_seconds=int(
            os.getenv("DOCFLOW_IDEMPOTENCY_STALE_SECONDS", str(30 * 60))
        ),
        enabled=os.getenv("DOCFLOW_IDEMPOTENCY_ENABLED", "1").strip() != "0",
    )



def normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = str(value).strip()
    return key or None



def build_business_idempotency_key(
    *,
    task_id: int | str,
    doc_type: str,
    document_number: str,
) -> str:
    """
    Удобный ключ для будущего UI/API, если нет внешнего ключа запроса.

    В основной flow он НЕ используется автоматически, чтобы обычные тестовые
    повторные сканы не превращались в replay. Вызывать явно.
    """

    return f"scan:{task_id}:{doc_type}:{document_number}"


def build_request_fingerprint(
    *,
    task_id: int | str,
    doc_type: str,
    document_number: str,
) -> str:
    """Строит стабильный fingerprint бизнес-параметров операции."""

    raw_doc_type = str(doc_type).strip()
    raw_document_number = str(document_number).strip()
    normalized_doc_type = normalize_doc_type(raw_doc_type)
    normalized_document_number = normalize_document_number(raw_document_number)

    # Keep the historical fingerprint for already-canonical values so existing
    # succeeded markers remain replayable after upgrade. Add raw identity only
    # when normalization is lossy, preventing '/' and '\\' from collapsing into
    # the same business document.
    canonical = {
        "task_id": str(task_id).strip(),
        "doc_type": normalized_doc_type,
        "document_number": normalized_document_number,
    }
    if raw_doc_type != normalized_doc_type:
        canonical["doc_type_raw"] = raw_doc_type
    if raw_document_number != normalized_document_number:
        canonical["document_number_raw"] = raw_document_number
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()



def build_record_path(record_dir: Path | str, idempotency_key: str) -> Path:
    record_dir = Path(record_dir)
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9А-Яа-яЁё._-]+", "_", idempotency_key).strip("._-")
    if not safe:
        safe = "key"
    safe = safe[:80]
    return record_dir / f"{safe}_{digest}.json"


def _ensure_recorded_path_within(
    *,
    raw_path: str | None,
    allowed_root: Path | str | None,
    path_kind: str,
    idempotency_key: str,
    record_path: Path,
    record: IdempotencyRecord,
) -> None:
    if not raw_path or allowed_root is None:
        return

    try:
        resolved_root = Path(allowed_root).resolve(strict=False)
        resolved_path = Path(raw_path).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise IdempotencyRecordError(
            code=f"idempotency_{path_kind}_path_resolve_error",
            operator_message="Запись идемпотентности содержит некорректный путь к PDF.",
            technical_message=str(exc),
            idempotency_key=idempotency_key,
            record_path=record_path,
            record=record.to_dict(),
        ) from exc

    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise IdempotencyRecordError(
            code=f"idempotency_{path_kind}_path_outside_allowed_root",
            operator_message="Запись идемпотентности содержит небезопасный путь к PDF.",
            technical_message=(
                f"Resolved {path_kind} path is outside allowed root: "
                f"path={resolved_path}; root={resolved_root}"
            ),
            idempotency_key=idempotency_key,
            record_path=record_path,
            record=record.to_dict(),
        )



def read_record(record_path: Path) -> IdempotencyRecord | None:
    if not record_path.exists():
        return None

    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("record json root is not an object")
        return IdempotencyRecord.from_dict(data)
    except Exception as exc:
        raise IdempotencyRecordError(
            code="idempotency_record_read_error",
            operator_message="Не удалось прочитать запись идемпотентности.",
            technical_message=str(exc),
            record_path=record_path,
        ) from exc



def write_record(record_path: Path, record: IdempotencyRecord, *, create_only: bool = False) -> None:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    data = record.to_dict()

    if create_only:
        temp_path = record_path.with_name(
            f".{record_path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        )
        try:
            with temp_path.open("x", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.link(str(temp_path), str(record_path))
            return
        except FileExistsError:
            raise
        except OSError as exc:
            raise IdempotencyRecordError(
                code="idempotency_record_create_error",
                operator_message="Не удалось атомарно создать запись идемпотентности.",
                technical_message=str(exc),
                idempotency_key=record.idempotency_key,
                record_path=record_path,
            ) from exc
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    temp_path = record_path.with_name(f".{record_path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(str(temp_path), str(record_path))
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise IdempotencyRecordError(
            code="idempotency_record_update_error",
            operator_message="Не удалось обновить запись идемпотентности.",
            technical_message=str(exc),
            idempotency_key=record.idempotency_key,
            record_path=record_path,
        ) from exc



def is_record_stale(record: IdempotencyRecord, settings: IdempotencySettings) -> bool:
    if record.hostname == socket.gethostname() and is_process_running(record.pid):
        return False
    updated_at = parse_datetime_utc(record.updated_at_utc)
    if updated_at is None:
        return True
    age_seconds = (utc_now() - updated_at).total_seconds()
    return age_seconds >= settings.in_progress_stale_after_seconds



def _new_processing_record(
    *,
    idempotency_key: str,
    operation_id: str,
    task_id: str,
    doc_type: str,
    document_number: str,
    request_fingerprint: str,
    attempt: int = 1,
) -> IdempotencyRecord:
    now = utc_now_iso()
    return IdempotencyRecord(
        idempotency_key=idempotency_key,
        status="processing",
        operation_id=operation_id,
        task_id=str(task_id),
        doc_type=str(doc_type),
        # Kept under the historical JSON field name for backward-compatible
        # recovery. New records fill it with the server-side scan start time.
        document_datetime="",
        document_number=str(document_number),
        expected_file_name="",
        request_fingerprint=request_fingerprint,
        attempt=attempt,
        pid=os.getpid(),
        hostname=socket.gethostname(),
        created_at_utc=now,
        updated_at_utc=now,
    )



def _with_updates(record: IdempotencyRecord, **updates: Any) -> IdempotencyRecord:
    data = record.to_dict()
    data.update(updates)
    data["updated_at_utc"] = utc_now_iso()
    return IdempotencyRecord.from_dict(data)



def begin_idempotent_operation(
    *,
    idempotency_key: str | None,
    operation_id: str,
    task_id: int | str,
    doc_type: str,
    document_number: str,
    settings: IdempotencySettings,
    incoming_dir: Path | str | None = None,
    archive_root: Path | str | None = None,
) -> IdempotencyDecision:
    """
    Решает, надо ли реально сканировать, вернуть старый результат или повторить storage.
    """

    normalized_key = normalize_idempotency_key(idempotency_key)
    if not settings.enabled or normalized_key is None:
        return IdempotencyDecision(mode="disabled")
    if settings.record_dir is None:
        raise IdempotencyRecordError(
            code="idempotency_directory_missing",
            operator_message="Не настроено хранилище состояния операций.",
            technical_message="IdempotencySettings.record_dir is None",
            idempotency_key=normalized_key,
        )

    record_path = build_record_path(settings.record_dir, normalized_key)
    request_fingerprint = build_request_fingerprint(
        task_id=task_id,
        doc_type=doc_type,
        document_number=document_number,
    )

    new_record = _new_processing_record(
        idempotency_key=normalized_key,
        operation_id=operation_id,
        task_id=str(task_id),
        doc_type=doc_type,
        document_number=document_number,
        request_fingerprint=request_fingerprint,
    )

    try:
        write_record(record_path, new_record, create_only=True)
        logger.info(
            "Idempotency record created idempotency_key=%s operation_id=%s record_path=%s",
            normalized_key,
            operation_id,
            record_path,
        )
        return IdempotencyDecision(mode="run_new_scan", record=new_record, record_path=record_path, reason="new_key")

    except FileExistsError:
        existing = read_record(record_path)
        if existing is None:
            # Гонка удаления/создания: пробуем ещё раз коротко.
            time.sleep(0.05)
            return begin_idempotent_operation(
                idempotency_key=normalized_key,
                operation_id=operation_id,
                task_id=task_id,
                doc_type=doc_type,
                document_number=document_number,
                settings=settings,
                incoming_dir=incoming_dir,
                archive_root=archive_root,
            )

    # Recalculate from the persisted business identity. Old releases included
    # Planfix document_datetime in the fingerprint; accepting the recalculated
    # value keeps their succeeded/recovery records usable after this upgrade.
    try:
        existing_fingerprint = build_request_fingerprint(
            task_id=existing.task_id,
            doc_type=existing.doc_type,
            document_number=existing.document_number,
        )
    except Exception as exc:
        raise IdempotencyRecordError(
            code="idempotency_record_fingerprint_error",
            operator_message="Запись идемпотентности содержит некорректные параметры документа.",
            technical_message=str(exc),
            idempotency_key=normalized_key,
            record_path=record_path,
            record=existing.to_dict(),
        ) from exc

    if not secrets.compare_digest(existing_fingerprint, request_fingerprint):
        raise IdempotencyConflictError(
            code="idempotency_key_request_conflict",
            operator_message="Этот ключ идемпотентности уже использован для другого документа.",
            technical_message=(
                "Idempotency key request fingerprint mismatch: "
                f"existing={existing_fingerprint} requested={request_fingerprint}"
            ),
            idempotency_key=normalized_key,
            record_path=record_path,
            record=existing.to_dict(),
        )

    if existing.request_fingerprint != existing_fingerprint:
        existing = replace(existing, request_fingerprint=existing_fingerprint)
        write_record(record_path, existing)

    _ensure_recorded_path_within(
        raw_path=existing.temp_scan_path,
        allowed_root=incoming_dir,
        path_kind="temp",
        idempotency_key=normalized_key,
        record_path=record_path,
        record=existing,
    )
    _ensure_recorded_path_within(
        raw_path=existing.final_file_path,
        allowed_root=archive_root,
        path_kind="final",
        idempotency_key=normalized_key,
        record_path=record_path,
        record=existing,
    )

    status = existing.status

    if status == "succeeded":
        final_path = Path(existing.final_file_path) if existing.final_file_path else None
        if final_path and final_path.exists():
            logger.info(
                "Idempotency replay existing result idempotency_key=%s operation_id=%s original_operation_id=%s final_file_path=%s",
                normalized_key,
                operation_id,
                existing.operation_id,
                final_path,
            )
            return IdempotencyDecision(
                mode="return_existing",
                record=existing,
                record_path=record_path,
                reason="already_succeeded",
            )

        raise IdempotencyError(
            code="manual_recovery_required",
            operator_message=(
                "Операция уже была завершена, но итоговый PDF сейчас недоступен. "
                "Повторное сканирование остановлено; требуется проверка архива."
            ),
            technical_message=(
                "Succeeded idempotency record has missing or unavailable final file: "
                f"{final_path}"
            ),
            idempotency_key=normalized_key,
            record_path=record_path,
            record=existing.to_dict(),
        )

    if status == "scanned":
        temp_path = Path(existing.temp_scan_path) if existing.temp_scan_path else None
        if temp_path and temp_path.exists():
            logger.info(
                "Idempotency retry storage from scanned temp idempotency_key=%s operation_id=%s temp_scan_path=%s",
                normalized_key,
                operation_id,
                temp_path,
            )
            retry_record = _with_updates(
                existing,
                status="storing",
                operation_id=operation_id,
                pid=os.getpid(),
                hostname=socket.gethostname(),
            )
            write_record(record_path, retry_record)
            return IdempotencyDecision(mode="retry_storage", record=retry_record, record_path=record_path, reason="scanned_temp_exists")

        replacement = _new_processing_record(
            idempotency_key=normalized_key,
            operation_id=operation_id,
            task_id=str(task_id),
            doc_type=doc_type,
            document_number=document_number,
            request_fingerprint=request_fingerprint,
            attempt=existing.attempt + 1,
        )
        write_record(record_path, replacement)
        return IdempotencyDecision(mode="run_new_scan", record=replacement, record_path=record_path, reason="missing_temp_file")

    if status in {"processing", "storing"}:
        if not is_record_stale(existing, settings):
            raise IdempotencyInProgressError(
                code="idempotency_in_progress",
                operator_message="Эта операция сканирования уже выполняется. Дождитесь завершения или выполните диагностику.",
                technical_message=f"Existing idempotency record status={status}",
                idempotency_key=normalized_key,
                record_path=record_path,
                record=existing.to_dict(),
            )

        # Старый storing с temp-файлом можно продолжить как retry storage.
        temp_path = Path(existing.temp_scan_path) if existing.temp_scan_path else None
        if status == "storing" and temp_path and temp_path.exists():
            retry_record = _with_updates(
                existing,
                status="storing",
                operation_id=operation_id,
                pid=os.getpid(),
                hostname=socket.gethostname(),
            )
            write_record(record_path, retry_record)
            return IdempotencyDecision(mode="retry_storage", record=retry_record, record_path=record_path, reason="stale_storing_retry")

        replacement = _new_processing_record(
            idempotency_key=normalized_key,
            operation_id=operation_id,
            task_id=str(task_id),
            doc_type=doc_type,
            document_number=document_number,
            request_fingerprint=request_fingerprint,
            attempt=existing.attempt + 1,
        )
        write_record(record_path, replacement)
        return IdempotencyDecision(mode="run_new_scan", record=replacement, record_path=record_path, reason="stale_in_progress")

    # failed / interrupted / timeout — разрешаем новую попытку с тем же ключом.
    replacement = _new_processing_record(
        idempotency_key=normalized_key,
        operation_id=operation_id,
        task_id=str(task_id),
        doc_type=doc_type,
        document_number=document_number,
        request_fingerprint=request_fingerprint,
        attempt=existing.attempt + 1,
    )
    write_record(record_path, replacement)
    return IdempotencyDecision(mode="run_new_scan", record=replacement, record_path=record_path, reason=f"previous_status_{status}")



def mark_scan_started(
    record_path: Path | None,
    record: IdempotencyRecord | None,
    *,
    scan_started_at: datetime | str,
    expected_file_name: str,
) -> IdempotencyRecord | None:
    if record_path is None or record is None:
        return None
    timestamp = parse_document_datetime(scan_started_at).isoformat(timespec="seconds")
    updated = _with_updates(
        record,
        document_datetime=timestamp,
        expected_file_name=expected_file_name,
    )
    write_record(record_path, updated)
    logger.info(
        "Idempotency scan start recorded idempotency_key=%s operation_id=%s scan_started_at=%s expected_file_name=%s",
        updated.idempotency_key,
        updated.operation_id,
        timestamp,
        expected_file_name,
    )
    return updated


def mark_scanned(record_path: Path | None, record: IdempotencyRecord | None, *, temp_scan_path: Path | str) -> IdempotencyRecord | None:
    if record_path is None or record is None:
        return None
    updated = _with_updates(record, status="scanned", temp_scan_path=str(temp_scan_path))
    write_record(record_path, updated)
    logger.info(
        "Idempotency marked scanned idempotency_key=%s operation_id=%s temp_scan_path=%s",
        updated.idempotency_key,
        updated.operation_id,
        temp_scan_path,
    )
    return updated



def mark_storing(
    record_path: Path | None,
    record: IdempotencyRecord | None,
    *,
    final_file_name: str | None = None,
    final_file_path: Path | str | None = None,
) -> IdempotencyRecord | None:
    if record_path is None or record is None:
        return None
    changes: dict[str, Any] = {"status": "storing"}
    if final_file_name is not None:
        changes["final_file_name"] = final_file_name
    if final_file_path is not None:
        changes["final_file_path"] = str(final_file_path)
    updated = _with_updates(record, **changes)
    write_record(record_path, updated)
    logger.info(
        "Idempotency marked storing idempotency_key=%s operation_id=%s final_file_path=%s",
        updated.idempotency_key,
        updated.operation_id,
        updated.final_file_path,
    )
    return updated



def mark_succeeded(
    record_path: Path | None,
    record: IdempotencyRecord | None,
    *,
    final_file_name: str,
    final_file_path: Path | str,
) -> IdempotencyRecord | None:
    if record_path is None or record is None:
        return None
    updated = _with_updates(
        record,
        status="succeeded",
        final_file_name=final_file_name,
        final_file_path=str(final_file_path),
        error_code=None,
        operator_message=None,
        technical_message=None,
    )
    write_record(record_path, updated)
    logger.info(
        "Idempotency marked succeeded idempotency_key=%s operation_id=%s final_file_path=%s",
        updated.idempotency_key,
        updated.operation_id,
        final_file_path,
    )
    return updated



def mark_failed(
    record_path: Path | None,
    record: IdempotencyRecord | None,
    *,
    status: IdempotencyStatus = "failed",
    error_code: str | None = None,
    operator_message: str | None = None,
    technical_message: str | None = None,
) -> IdempotencyRecord | None:
    if record_path is None or record is None:
        return None
    updated = _with_updates(
        record,
        status=status,
        error_code=error_code,
        operator_message=operator_message,
        technical_message=technical_message,
    )
    write_record(record_path, updated)
    logger.warning(
        "Idempotency marked failed idempotency_key=%s operation_id=%s status=%s error_code=%s",
        updated.idempotency_key,
        updated.operation_id,
        status,
        error_code,
    )
    return updated
