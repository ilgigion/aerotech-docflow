from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import shutil
import tempfile

import app.document_flow as df
from app.idempotency import IdempotencySettings
from app.scanner import ScannerSettings
from app.storage import StorageSettings, StoredDocument


class Counter:
    scan_count = 0
    store_count = 0


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="docflow_idempotent_flow_"))
    old_scan_document = df.scan_document
    old_store_document = df.store_document
    old_log_dir = os.environ.get("DOCFLOW_LOG_DIR")

    try:
        incoming = root / "incoming"
        archive = root / "archive"
        incoming.mkdir()
        archive.mkdir()
        os.environ["DOCFLOW_LOG_DIR"] = str(root / "logs")

        def fake_scan_document(task_id, settings=None, operation_id=None):
            Counter.scan_count += 1
            path = incoming / f"PF_{task_id}_{Counter.scan_count}.pdf"
            path.write_bytes(b"%PDF-1.4\n% fake scan\n")
            return path

        def fake_store_document(source_path, doc_type, document_datetime, document_number, settings=None, operation_id=None):
            Counter.store_count += 1
            destination = archive / f"result_{Counter.store_count}.pdf"
            shutil.move(str(source_path), str(destination))
            return StoredDocument(file_name=destination.name, file_path=destination)

        df.scan_document = fake_scan_document
        df.store_document = fake_store_document

        scanner_settings = ScannerSettings(incoming_dir=incoming)
        storage_settings = StorageSettings(archive_root=archive)
        idempotency_settings = IdempotencySettings(record_dir=incoming / "_idempotency")

        first = df.process_document_scan(
            task_id="TASK-IDEM",
            doc_type="УПД",
            document_datetime=datetime(2026, 7, 10, 10, 10, 25),
            document_number="2455B",
            scanner_settings=scanner_settings,
            storage_settings=storage_settings,
            use_lock=False,
            idempotency_key="KEY-FLOW-001",
            idempotency_settings=idempotency_settings,
        )

        second = df.process_document_scan(
            task_id="TASK-IDEM",
            doc_type="УПД",
            document_datetime=datetime(2026, 7, 10, 10, 10, 25),
            document_number="2455B",
            scanner_settings=scanner_settings,
            storage_settings=storage_settings,
            use_lock=False,
            idempotency_key="KEY-FLOW-001",
            idempotency_settings=idempotency_settings,
        )

        assert Counter.scan_count == 1, f"scan must run once, got {Counter.scan_count}"
        assert Counter.store_count == 1, f"store must run once, got {Counter.store_count}"
        assert first.file_path == second.file_path
        assert second.idempotent_replay is True

        log_files = list((root / "logs").glob("docflow_*.txt"))
        assert log_files, "monthly txt log was not created"
        log_text = "\n".join(path.read_text(encoding="utf-8") for path in log_files)
        assert "Document scan process started" in log_text
        assert "Idempotency replay existing result" in log_text

        print("OK")
        print("Idempotent document flow fake test passed")
        print(f"first_file: {first.file_path}")
        print(f"second_file: {second.file_path}")

    finally:
        df.scan_document = old_scan_document
        df.store_document = old_store_document
        if old_log_dir is None:
            os.environ.pop("DOCFLOW_LOG_DIR", None)
        else:
            os.environ["DOCFLOW_LOG_DIR"] = old_log_dir
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
