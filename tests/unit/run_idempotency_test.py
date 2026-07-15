from datetime import datetime
from pathlib import Path
import tempfile

from app.idempotency import (
    IdempotencySettings,
    begin_idempotent_operation,
    mark_scanned,
    mark_succeeded,
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
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        expected_file_name="УПД_260710_101025_2455B.pdf",
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

    decision2 = begin_idempotent_operation(
        idempotency_key=key,
        operation_id="OP2",
        task_id="TASK1",
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        expected_file_name="УПД_260710_101025_2455B.pdf",
        settings=settings,
    )
    assert decision2.mode == "return_existing"

print("OK: idempotency")
