from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from app.idempotency import (
    IdempotencyInProgressError,
    IdempotencySettings,
    begin_idempotent_operation,
    mark_scanned,
    mark_succeeded,
)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="docflow_idempotency_unit_"))
    try:
        settings = IdempotencySettings(record_dir=root / "idem", in_progress_stale_after_seconds=60)

        decision1 = begin_idempotent_operation(
            idempotency_key="KEY-001",
            operation_id="OP1",
            task_id="TASK1",
            doc_type="УПД",
            document_datetime="2026-07-10 10:10:25",
            document_number="2455B",
            expected_file_name="УПД_260710_101025_2455B.pdf",
            settings=settings,
        )
        assert decision1.mode == "run_new_scan"
        assert decision1.record is not None
        assert decision1.record_path is not None

        try:
            begin_idempotent_operation(
                idempotency_key="KEY-001",
                operation_id="OP2",
                task_id="TASK1",
                doc_type="УПД",
                document_datetime="2026-07-10 10:10:25",
                document_number="2455B",
                expected_file_name="УПД_260710_101025_2455B.pdf",
                settings=settings,
            )
        except IdempotencyInProgressError:
            pass
        else:
            raise AssertionError("In-progress idempotency record must block duplicate run")

        temp_pdf = root / "PF_TEST.pdf"
        temp_pdf.write_bytes(b"%PDF-1.4\n% fake\n")
        scanned_record = mark_scanned(decision1.record_path, decision1.record, temp_scan_path=temp_pdf)
        assert scanned_record is not None

        decision2 = begin_idempotent_operation(
            idempotency_key="KEY-001",
            operation_id="OP3",
            task_id="TASK1",
            doc_type="УПД",
            document_datetime="2026-07-10 10:10:25",
            document_number="2455B",
            expected_file_name="УПД_260710_101025_2455B.pdf",
            settings=settings,
        )
        assert decision2.mode == "retry_storage"

        final_pdf = root / "archive" / "УПД_260710_101025_2455B.pdf"
        final_pdf.parent.mkdir(parents=True, exist_ok=True)
        final_pdf.write_bytes(b"%PDF-1.4\n% fake final\n")
        succeeded = mark_succeeded(
            decision2.record_path,
            decision2.record,
            final_file_name=final_pdf.name,
            final_file_path=final_pdf,
        )
        assert succeeded is not None

        decision3 = begin_idempotent_operation(
            idempotency_key="KEY-001",
            operation_id="OP4",
            task_id="TASK1",
            doc_type="УПД",
            document_datetime="2026-07-10 10:10:25",
            document_number="2455B",
            expected_file_name="УПД_260710_101025_2455B.pdf",
            settings=settings,
        )
        assert decision3.mode == "return_existing"

        print("OK")
        print("Idempotency unit test passed")

    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
