from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile

from app.idempotency import (
    IdempotencyConflictError,
    IdempotencySettings,
    begin_idempotent_operation,
    build_request_fingerprint,
    mark_scanned,
    mark_succeeded,
    read_record,
    write_record,
)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    settings = IdempotencySettings(record_dir=root / "idem")
    key = "unit:scan:1"

    decision1 = begin_idempotent_operation(
        idempotency_key=key,
        operation_id="OP1",
        task_id="TASK1",
        doc_type="УПД",
        document_number="2455B",
        scanner_profile="EPSON A",
        settings=settings,
    )
    assert decision1.mode == "run_new_scan"
    assert decision1.record is not None
    assert decision1.record_path is not None

    temp_pdf = root / "scan.pdf"
    final_pdf = root / "archive" / "done.pdf"
    final_pdf.parent.mkdir()
    temp_pdf.write_bytes(b"%PDF-1.4\nidem\n%%EOF\n")
    final_pdf.write_bytes(b"%PDF-1.4\nidem\n%%EOF\n")

    record = mark_scanned(decision1.record_path, decision1.record, temp_scan_path=temp_pdf)
    record = mark_succeeded(decision1.record_path, record, final_file_name=final_pdf.name, final_file_path=final_pdf)
    assert record is not None

    # Simulate a record written by the previous release, whose fingerprint
    # included Planfix document_datetime. It must remain replayable after the
    # HTTP field is removed.
    legacy_payload = json.dumps(
        {
            "task_id": "TASK1",
            "doc_type": "УПД",
            "document_datetime": "2026-07-10T10:10:25",
            "document_number": "2455B",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    legacy_fingerprint = hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()
    record = replace(
        record,
        document_datetime="2026-07-10T10:10:25",
        scanner_profile="",
        request_fingerprint=legacy_fingerprint,
    )
    write_record(decision1.record_path, record)

    decision2 = begin_idempotent_operation(
        idempotency_key=key,
        operation_id="OP2",
        task_id="TASK1",
        doc_type="УПД",
        document_number="2455B",
        scanner_profile="EPSON A",
        settings=settings,
    )
    assert decision2.mode == "return_existing"
    migrated = read_record(decision1.record_path)
    assert migrated is not None
    assert migrated.request_fingerprint == build_request_fingerprint(
        task_id="TASK1",
        doc_type="УПД",
        document_number="2455B",
        scanner_profile="EPSON A",
    )
    assert migrated.scanner_profile == "EPSON A"

    try:
        begin_idempotent_operation(
            idempotency_key=key,
            operation_id="OP-PROFILE-CONFLICT",
            task_id="TASK1",
            doc_type="УПД",
            document_number="2455B",
            scanner_profile="EPSON B",
            settings=settings,
        )
        raise AssertionError("Expected IdempotencyConflictError for another scanner profile")
    except IdempotencyConflictError as exc:
        assert exc.code == "idempotency_key_request_conflict"

    try:
        begin_idempotent_operation(
            idempotency_key=key,
            operation_id="OP3",
            task_id="TASK1",
            doc_type="УПД",
            document_number="DIFFERENT",
            scanner_profile="EPSON A",
            settings=settings,
        )
        raise AssertionError("Expected IdempotencyConflictError")
    except IdempotencyConflictError as exc:
        assert exc.code == "idempotency_key_request_conflict"

print("OK: idempotency")
