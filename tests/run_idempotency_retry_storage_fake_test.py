from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import tempfile

import app.document_flow as df
from app.idempotency import IdempotencySettings
from app.scanner import ScannerSettings
from app.storage import StorageError, StorageSettings, StoredDocument


class Counter:
    scan_count = 0
    store_count = 0


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="docflow_idempotent_retry_"))
    old_scan_document = df.scan_document
    old_store_document = df.store_document

    try:
        incoming = root / "incoming"
        archive = root / "archive"
        incoming.mkdir()
        archive.mkdir()

        def fake_scan_document(task_id, settings=None, operation_id=None):
            Counter.scan_count += 1
            path = incoming / f"PF_{task_id}_{Counter.scan_count}.pdf"
            path.write_bytes(b"%PDF-1.4\n% fake scan\n")
            return path

        def fake_store_document(source_path, doc_type, document_datetime, document_number, settings=None, operation_id=None):
            Counter.store_count += 1
            if Counter.store_count == 1:
                raise StorageError(
                    code="fake_storage_error",
                    operator_message="Fake storage error",
                    technical_message="First storage attempt intentionally failed",
                    source_path=Path(source_path),
                )
            destination = archive / "result_after_retry.pdf"
            shutil.move(str(source_path), str(destination))
            return StoredDocument(file_name=destination.name, file_path=destination)

        df.scan_document = fake_scan_document
        df.store_document = fake_store_document

        scanner_settings = ScannerSettings(incoming_dir=incoming)
        storage_settings = StorageSettings(archive_root=archive)
        idempotency_settings = IdempotencySettings(record_dir=incoming / "_idempotency")

        try:
            df.process_document_scan(
                task_id="TASK-RETRY",
                doc_type="УПД",
                document_datetime=datetime(2026, 7, 10, 10, 10, 25),
                document_number="2455B",
                scanner_settings=scanner_settings,
                storage_settings=storage_settings,
                use_lock=False,
                idempotency_key="KEY-RETRY-001",
                idempotency_settings=idempotency_settings,
            )
        except StorageError:
            pass
        else:
            raise AssertionError("First storage attempt must fail")

        second = df.process_document_scan(
            task_id="TASK-RETRY",
            doc_type="УПД",
            document_datetime=datetime(2026, 7, 10, 10, 10, 25),
            document_number="2455B",
            scanner_settings=scanner_settings,
            storage_settings=storage_settings,
            use_lock=False,
            idempotency_key="KEY-RETRY-001",
            idempotency_settings=idempotency_settings,
        )

        assert Counter.scan_count == 1, f"scan must not repeat, got {Counter.scan_count}"
        assert Counter.store_count == 2, f"storage must retry, got {Counter.store_count}"
        assert second.file_path.exists()

        print("OK")
        print("Idempotency retry storage fake test passed")
        print(f"final_file: {second.file_path}")

    finally:
        df.scan_document = old_scan_document
        df.store_document = old_store_document
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
