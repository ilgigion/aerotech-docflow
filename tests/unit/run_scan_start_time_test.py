from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from pypdf import PdfWriter

import app.document_flow as document_flow
from app.idempotency import IdempotencySettings, build_record_path, read_record
from app.monthly_file_logging import close_monthly_file_logging
from app.scanner import ScannerSettings
from app.storage import StorageSettings


MOSCOW = ZoneInfo("Europe/Moscow")
FIXED_SCAN_START = datetime(2026, 7, 22, 9, 8, 7, tzinfo=MOSCOW)


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    incoming = root / "incoming"
    archive = root / "archive"
    records = root / "idempotency"
    incoming.mkdir()
    scan_calls = 0

    def fake_scan_document(*, task_id, settings, operation_id, on_scan_start):
        del task_id, operation_id
        global scan_calls
        scan_calls += 1
        on_scan_start()
        output = settings.incoming_dir / "PF_SERVER_TIME_TEST.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with output.open("wb") as stream:
            writer.write(stream)
        return output

    original_scan = document_flow.scan_document
    original_clock = document_flow.current_moscow_time
    document_flow.scan_document = fake_scan_document
    document_flow.current_moscow_time = lambda: FIXED_SCAN_START
    try:
        arguments = {
            "task_id": "SERVER-TIME-1",
            "doc_type": "НКЛ",
            "document_number": "001",
            "scanner_settings": ScannerSettings(incoming_dir=incoming),
            "storage_settings": StorageSettings(archive_root=archive),
            "use_lock": False,
            "idempotency_key": "server-time-test-1",
            "idempotency_settings": IdempotencySettings(record_dir=records),
        }
        first = document_flow.process_document_scan(**arguments)
        second = document_flow.process_document_scan(**arguments)
    finally:
        document_flow.scan_document = original_scan
        document_flow.current_moscow_time = original_clock
        close_monthly_file_logging()

    assert first.file_name == "НКЛ_260722_090807_001.pdf"
    assert first.file_path == archive / "2026" / "НКЛ" / first.file_name
    assert second.file_name == first.file_name
    assert second.idempotent_replay is True
    assert scan_calls == 1

    record = read_record(build_record_path(records, "server-time-test-1"))
    assert record is not None
    assert record.document_datetime == "2026-07-22T09:08:07+03:00"
    assert record.expected_file_name == first.file_name

print("OK: filename uses server-side Europe/Moscow physical scan start")
