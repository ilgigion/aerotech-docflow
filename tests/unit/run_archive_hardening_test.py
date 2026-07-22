from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
import tempfile

from app.api import ScanRequest, validate_document_identity
from app.idempotency import (
    IdempotencyError,
    IdempotencyRecord,
    IdempotencySettings,
    begin_idempotent_operation,
    build_record_path,
    build_request_fingerprint,
    is_record_stale,
    write_record,
)
from app.locks import (
    _write_lock_file_atomically,
    build_lock_info,
    is_lock_stale,
    read_lock_info,
)
from app.production_config import (
    ProductionConfigurationError,
    validate_runtime_environment,
)
from app.scanner_recovery import cleanup_archive_artifacts
from app.storage import (
    DestinationReservation,
    FileMoveError,
    release_destination_reservation,
    verify_copied_file,
)


assert build_request_fingerprint(
    task_id="T1",
    doc_type="НКЛ",
    document_number="A/B",
) != build_request_fingerprint(
    task_id="T1",
    doc_type="НКЛ",
    document_number="A\\B",
)

try:
    validate_document_identity(
        ScanRequest(
            task_id="T1",
            doc_type="НКЛ",
            document_number="A/B",
        )
    )
    raise AssertionError("Lossy document identity must be rejected")
except ValueError:
    pass

assert not is_lock_stale({"invalid_lock_file": True}, stale_after_seconds=0)
assert not is_lock_stale({"unreadable_lock_file": True}, stale_after_seconds=0)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    records = root / "records"
    archive = root / "archive"
    incoming = root / "incoming"
    records.mkdir()
    archive.mkdir()
    incoming.mkdir()

    concurrent_lock = root / ".concurrent-scanner.lock"

    def publish_lock(index: int) -> str:
        try:
            _write_lock_file_atomically(
                concurrent_lock,
                build_lock_info(f"OP-{index}", f"TASK-{index}"),
            )
            return "created"
        except FileExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=12) as pool:
        lock_results = list(pool.map(publish_lock, range(12)))
    assert lock_results.count("created") == 1
    assert lock_results.count("exists") == 11
    lock_info = read_lock_info(concurrent_lock)
    assert lock_info and not lock_info.get("invalid_lock_file")

    concurrent_record_path = records / "concurrent.json"
    concurrent_record = IdempotencyRecord(
        idempotency_key="concurrent",
        status="processing",
        operation_id="CONCURRENT",
        task_id="TASK",
        doc_type="НКЛ",
        document_datetime="",
        document_number="001",
        expected_file_name="file.pdf",
    )

    def publish_record(_: int) -> str:
        try:
            write_record(concurrent_record_path, concurrent_record, create_only=True)
            return "created"
        except FileExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=12) as pool:
        record_results = list(pool.map(publish_record, range(12)))
    assert record_results.count("created") == 1
    assert record_results.count("exists") == 11
    parsed_record = json.loads(concurrent_record_path.read_text(encoding="utf-8"))
    assert parsed_record["operation_id"] == "CONCURRENT"

    fingerprint = build_request_fingerprint(
        task_id="TASK",
        doc_type="НКЛ",
        document_number="001",
    )
    record = IdempotencyRecord(
        idempotency_key="missing-final",
        status="succeeded",
        operation_id="OLD",
        task_id="TASK",
        doc_type="НКЛ",
        document_datetime="2026-07-16T12:00:00",
        document_number="001",
        expected_file_name="НКЛ_260716_120000_001.pdf",
        request_fingerprint=fingerprint,
        final_file_name="НКЛ_260716_120000_001.pdf",
        final_file_path=str(archive / "2026" / "НКЛ" / "НКЛ_260716_120000_001.pdf"),
    )
    record_path = build_record_path(records, record.idempotency_key)
    write_record(record_path, record)
    try:
        begin_idempotent_operation(
            idempotency_key=record.idempotency_key,
            operation_id="NEW",
            task_id=record.task_id,
            doc_type=record.doc_type,
            document_number=record.document_number,
            settings=IdempotencySettings(record_dir=records),
            incoming_dir=incoming,
            archive_root=archive,
        )
        raise AssertionError("Missing succeeded PDF must not start a new scan")
    except IdempotencyError as exc:
        assert exc.code == "manual_recovery_required"

    live_record = IdempotencyRecord(
        idempotency_key="live",
        status="storing",
        operation_id="LIVE",
        task_id="TASK",
        doc_type="НКЛ",
        document_datetime="2026-07-16T12:00:00",
        document_number="001",
        expected_file_name="file.pdf",
        pid=os.getpid(),
        hostname=socket.gethostname(),
        updated_at_utc=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    assert not is_record_stale(
        live_record,
        IdempotencySettings(record_dir=records, in_progress_stale_after_seconds=0),
    )

    source = root / "source.pdf"
    copied = root / "copied.pdf"
    source.write_bytes(b"%PDF-" + b"A" * 100)
    copied.write_bytes(b"%PDF-" + b"B" * 100)
    try:
        verify_copied_file(source, copied)
        raise AssertionError("Same-size corrupted copy must be rejected")
    except FileMoveError as exc:
        assert exc.code == "atomic_temp_hash_mismatch"

    archive_artifacts = root / "archive_artifacts"
    archive_artifacts.mkdir()
    arbitrary_tmp = archive_artifacts / "business.tmp"
    arbitrary_reserve = archive_artifacts / "business.reserve"
    managed_tmp = archive_artifacts / ".document.pdf.123456abcdef.tmp"
    destination = archive_artifacts / "document.pdf"
    managed_reserve = archive_artifacts / ".document.pdf.reserve"
    reservation_stage = (
        archive_artifacts / "..staged.pdf.reserve.99999999.123456abcdef.tmp"
    )
    arbitrary_tmp.write_text("keep", encoding="utf-8")
    arbitrary_reserve.write_text("keep", encoding="utf-8")
    managed_tmp.write_text("managed", encoding="utf-8")
    managed_reserve.write_text(
        json.dumps(
            {
                "operation_id": "DEAD",
                "destination_path": str(destination),
                "pid": 99999999,
                "hostname": socket.gethostname(),
                "created_at_utc": "2000-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    reservation_stage.write_text(
        json.dumps(
            {
                "operation_id": "DEAD-STAGE",
                "destination_path": str(archive_artifacts / "staged.pdf"),
                "pid": 99999999,
                "hostname": socket.gethostname(),
                "created_at_utc": "2000-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    removed = cleanup_archive_artifacts(
        archive_artifacts,
        stale_after_seconds=0,
    )
    assert removed == [managed_reserve, reservation_stage]
    assert arbitrary_tmp.exists() and arbitrary_reserve.exists() and managed_tmp.exists()
    removed = cleanup_archive_artifacts(
        archive_artifacts,
        stale_after_seconds=0,
        remove_unowned_temp=True,
    )
    assert removed == [managed_tmp]

    owned_reserve = archive_artifacts / ".owned.pdf.reserve"
    owned_reserve.write_text(
        json.dumps(
            {
                "operation_id": "NEW_OWNER",
                "destination_path": str(archive_artifacts / "owned.pdf"),
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    release_destination_reservation(
        DestinationReservation(
            destination_path=archive_artifacts / "owned.pdf",
            reservation_path=owned_reserve,
            operation_id="OLD_OWNER",
            pid=os.getpid(),
            hostname=socket.gethostname(),
        )
    )
    assert owned_reserve.exists()

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    archive = root / "real_archive"
    incoming = root / "incoming"
    logs = root / "logs"
    records = root / "records"
    for path in (archive, incoming, logs, records):
        path.mkdir()
    naps2 = root / "NAPS2.Console.exe"
    naps2.write_bytes(b"test executable marker")
    (archive / ".aerotech-docflow-archive.json").write_text(
        json.dumps(
            {
                "marker": "aerotech-docflow-archive-v1",
                "archive_id": "unit-real-archive",
            }
        ),
        encoding="utf-8",
    )

    original_environment = os.environ.copy()
    try:
        os.environ.update(
            {
                "DOCFLOW_ENV": "production",
                "DOCFLOW_VERSION": "1.0.0-rc1-test",
                "DOCFLOW_HOST": "127.0.0.1",
                "DOCFLOW_PORT": "8000",
                "ARCHIVE_ROOT": str(archive),
                "DOCFLOW_ARCHIVE_CONFIRMATION": str(archive.resolve()),
                "DOCFLOW_ARCHIVE_ID": "unit-real-archive",
                "SCANNER_INCOMING_DIR": str(incoming),
                "NAPS2_EXECUTABLE": str(naps2),
                "NAPS2_PROFILE": "TEST PROFILE",
                "NAPS2_OUTPUT_ENCODING": "utf-8",
                "SCANNER_TIMEOUT_SECONDS": "180",
                "SCANNER_TIMEOUT_KILL_GRACE_SECONDS": "10",
                "SCANNER_VERIFY_PROCESS_EXIT_SECONDS": "5",
                "SCANNER_QUARANTINE_FAILED_OUTPUTS": "1",
                "SCANNER_FAILED_SCAN_DIR_NAME": "_failed_runtime",
                "SCANNER_MIN_PDF_SIZE_BYTES": "100",
                "SCANNER_MIN_PDF_PAGES": "1",
                "SCANNER_STABLE_CHECKS": "2",
                "SCANNER_STABLE_INTERVAL_SECONDS": "0.5",
                "DOCFLOW_LOG_DIR": str(logs),
                "DOCFLOW_LOG_LEVEL": "INFO",
                "DOCFLOW_LOG_MAX_BYTES": "52428800",
                "DOCFLOW_LOG_BACKUP_COUNT": "5",
                "DOCFLOW_LOG_RETENTION_MONTHS": "12",
                "DOCFLOW_IDEMPOTENCY_DIR": str(records),
                "DOCFLOW_ALLOWED_DOC_TYPES": "НКЛ,УПД",
                "DOCFLOW_MIN_DOCUMENT_YEAR": "2020",
                "DOCFLOW_MAX_DOCUMENT_YEAR": "2030",
                "DOCFLOW_IDEMPOTENCY_ENABLED": "1",
                "DOCFLOW_MONTHLY_FILE_LOGS": "1",
                "DOCFLOW_IDEMPOTENCY_STALE_SECONDS": "1800",
                "STORAGE_RESERVATION_STALE_AFTER_SECONDS": "1800",
                "STORAGE_COPY_BUFFER_SIZE": "1048576",
                "STORAGE_KEEP_TEMP_ON_ERROR": "0",
                "SCANNER_LOCK_STALE_SECONDS": "1800",
                "SCANNER_LOCK_WAIT_TIMEOUT_SECONDS": "0",
                "SCANNER_LOCK_RETRY_INTERVAL_SECONDS": "0.5",
                "SCANNER_LOCK_ALLOW_STALE_TAKEOVER": "1",
                "INCOMING_CLEANUP_QUARANTINE_DIR_NAME": "_failed",
                "INCOMING_CLEANUP_MANAGED_PREFIX": "PF_",
                "INCOMING_CLEANUP_MANAGED_SUFFIX": ".pdf",
                "INCOMING_CLEANUP_MIN_AGE_SECONDS": "86400",
                "INCOMING_CLEANUP_SKIP_IF_LOCK_EXISTS": "1",
                "INCOMING_CLEANUP_STABLE_CHECKS": "2",
                "INCOMING_CLEANUP_STABLE_INTERVAL_SECONDS": "0.2",
            }
        )
        config = validate_runtime_environment()
        assert config.production and config.archive_root == archive

        os.environ["DOCFLOW_ARCHIVE_CONFIRMATION"] = str(root / "wrong")
        try:
            validate_runtime_environment()
            raise AssertionError("Mismatched archive confirmation must fail")
        except ProductionConfigurationError:
            pass
    finally:
        os.environ.clear()
        os.environ.update(original_environment)

print("OK: production archive hardening")
