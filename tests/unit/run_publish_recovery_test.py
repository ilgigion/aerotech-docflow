from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfWriter

from app.document_flow import _storage_retry_from_idempotency_record
from app.idempotency import IdempotencyError, IdempotencyRecord, build_record_path, write_record
from app.scanner import ScannerSettings
from app.storage import StorageSettings


def create_pdf(path: Path, pages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    incoming = root / "incoming"
    archive = root / "archive"
    records = root / "records"
    source = incoming / "PF_RECOVERY.pdf"
    final = archive / "2026" / "НКЛ" / "НКЛ_260716_124000_010.pdf"
    create_pdf(source, 1)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(source.read_bytes())

    record = IdempotencyRecord(
        idempotency_key="publish-recovery",
        status="storing",
        operation_id="OLD_OPERATION",
        task_id="ACC-010",
        doc_type="НКЛ",
        document_datetime="2026-07-16T12:40:00",
        document_number="010",
        expected_file_name=final.name,
        temp_scan_path=str(source),
        final_file_name=final.name,
        final_file_path=str(final),
    )
    record_path = build_record_path(records, record.idempotency_key)
    write_record(record_path, record)

    result = _storage_retry_from_idempotency_record(
        task_id=record.task_id,
        operation_id="RECOVERY_OPERATION",
        record=record,
        record_path=record_path,
        doc_type=record.doc_type,
        document_number=record.document_number,
        scanner_settings=ScannerSettings(incoming_dir=incoming),
        storage_settings=StorageSettings(archive_root=archive),
    )
    assert result.file_path == final
    assert result.idempotent_replay is True
    assert not source.exists()
    assert list(archive.rglob("*.pdf")) == [final]

with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    incoming = root / "incoming"
    archive = root / "archive"
    records = root / "records"
    source = incoming / "PF_MISMATCH.pdf"
    final = archive / "2026" / "НКЛ" / "НКЛ_260716_124000_011.pdf"
    create_pdf(source, 1)
    create_pdf(final, 2)
    record = IdempotencyRecord(
        idempotency_key="publish-mismatch",
        status="storing",
        operation_id="OLD_OPERATION",
        task_id="ACC-011",
        doc_type="НКЛ",
        document_datetime="2026-07-16T12:40:00",
        document_number="011",
        expected_file_name=final.name,
        temp_scan_path=str(source),
        final_file_name=final.name,
        final_file_path=str(final),
    )
    record_path = build_record_path(records, record.idempotency_key)
    write_record(record_path, record)
    try:
        _storage_retry_from_idempotency_record(
            task_id=record.task_id,
            operation_id="RECOVERY_OPERATION",
            record=record,
            record_path=record_path,
            doc_type=record.doc_type,
            document_number=record.document_number,
            scanner_settings=ScannerSettings(incoming_dir=incoming),
            storage_settings=StorageSettings(archive_root=archive),
        )
    except IdempotencyError as exc:
        assert exc.code == "idempotency_published_file_mismatch"
    else:
        raise AssertionError("Mismatched published file must stop automatic recovery")
    assert source.exists()
    assert len(list(archive.rglob("*.pdf"))) == 1

print("OK: published PDF recovery is idempotent")
