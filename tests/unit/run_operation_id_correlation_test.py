from pathlib import Path
from tempfile import TemporaryDirectory

import app.document_flow as document_flow
from app.idempotency import IdempotencySettings
from app.monthly_file_logging import close_monthly_file_logging
from app.scanner import ScannerNoPagesError, ScannerSettings
from app.storage import StorageSettings


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    incoming = root / "incoming"
    archive = root / "archive"
    incoming.mkdir()
    captured: dict[str, str] = {}

    def failed_scan(*, task_id: str, settings: ScannerSettings, operation_id: str, on_scan_start) -> Path:
        del task_id, settings
        on_scan_start()
        captured["operation_id"] = operation_id
        raise ScannerNoPagesError(
            code="no_scanned_pages",
            operator_message="No pages",
            output_path=incoming / "missing.pdf",
        )

    original_scan = document_flow.scan_document
    document_flow.scan_document = failed_scan
    try:
        result = document_flow.process_document_scan_safe(
            task_id="CORRELATION-1",
            doc_type="НКЛ",
            document_number="001",
            scanner_settings=ScannerSettings(incoming_dir=incoming),
            storage_settings=StorageSettings(archive_root=archive),
            use_lock=False,
            idempotency_key=None,
            idempotency_settings=IdempotencySettings(enabled=False),
        )
    finally:
        document_flow.scan_document = original_scan

    assert result.success is False
    assert result.error_code == "no_scanned_pages"
    assert result.operation_id == captured["operation_id"]
    close_monthly_file_logging()

print("OK: error response operation_id matches document flow")
