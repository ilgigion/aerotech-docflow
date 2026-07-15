from pathlib import Path
from datetime import datetime
import tempfile

from app.document_flow import _resolve_idempotency_path_within
from app.idempotency import (
    IdempotencyError,
    IdempotencyRecord,
    IdempotencyRecordError,
    IdempotencySettings,
    begin_idempotent_operation,
    mark_scanned,
    mark_succeeded,
)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    incoming = root / "incoming"
    archive = root / "archive"
    outside = root / "outside"
    incoming.mkdir()
    archive.mkdir()
    outside.mkdir()

    record = IdempotencyRecord(
        idempotency_key="path-test",
        status="scanned",
        operation_id="OP",
        task_id="TASK",
        doc_type="УПД",
        document_datetime="2026-07-10 10:10:25",
        document_number="2455B",
        expected_file_name="УПД_260710_101025_2455B.pdf",
    )

    safe_temp = incoming / "PF_TASK.pdf"
    assert _resolve_idempotency_path_within(
        raw_path=str(safe_temp),
        allowed_root=incoming,
        path_kind="temp",
        record=record,
    ) == safe_temp.resolve()

    for unsafe_path, kind, allowed_root in [
        (outside / "PF_STOLEN.pdf", "temp", incoming),
        (outside / "foreign.pdf", "final", archive),
    ]:
        try:
            _resolve_idempotency_path_within(
                raw_path=str(unsafe_path),
                allowed_root=allowed_root,
                path_kind=kind,
                record=record,
            )
            raise AssertionError("Expected unsafe idempotency path rejection")
        except IdempotencyError as exc:
            assert exc.code.endswith("_path_outside_allowed_root")

    settings = IdempotencySettings(record_dir=root / "idem")
    request_args = {
        "task_id": "TASK",
        "doc_type": "УПД",
        "document_datetime": datetime(2026, 7, 10, 10, 10, 25),
        "document_number": "2455B",
        "expected_file_name": "УПД_260710_101025_2455B.pdf",
        "settings": settings,
        "incoming_dir": incoming,
        "archive_root": archive,
    }

    temp_decision = begin_idempotent_operation(
        idempotency_key="unsafe-temp",
        operation_id="TEMP1",
        **request_args,
    )
    mark_scanned(
        temp_decision.record_path,
        temp_decision.record,
        temp_scan_path=outside / "PF_STOLEN.pdf",
    )
    try:
        begin_idempotent_operation(
            idempotency_key="unsafe-temp",
            operation_id="TEMP2",
            **request_args,
        )
        raise AssertionError("Expected stored temp path rejection")
    except IdempotencyRecordError as exc:
        assert exc.code == "idempotency_temp_path_outside_allowed_root"

    final_decision = begin_idempotent_operation(
        idempotency_key="unsafe-final",
        operation_id="FINAL1",
        **request_args,
    )
    mark_succeeded(
        final_decision.record_path,
        final_decision.record,
        final_file_name="foreign.pdf",
        final_file_path=outside / "foreign.pdf",
    )
    try:
        begin_idempotent_operation(
            idempotency_key="unsafe-final",
            operation_id="FINAL2",
            **request_args,
        )
        raise AssertionError("Expected stored final path rejection")
    except IdempotencyRecordError as exc:
        assert exc.code == "idempotency_final_path_outside_allowed_root"

print("OK: idempotency path safety")
