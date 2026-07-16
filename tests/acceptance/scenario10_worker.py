from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pypdf import PdfWriter

import app.document_flow as document_flow
import app.storage as storage_module
from app.idempotency import IdempotencySettings
from app.locks import ScannerLockSettings
from app.scanner import ScannerSettings
from app.storage import StorageSettings


def write_marker(path: Path, **data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": os.getpid(), **data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_scan_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    # Файл должен быть больше одного copy-буфера, но оставаться строгим PDF.
    for _ in range(1000):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)


def run(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    incoming = root / "incoming"
    archive = root / "archive"
    records = root / "idempotency"
    logs = root / "logs"
    for path in (incoming, archive, records, logs):
        path.mkdir(parents=True, exist_ok=True)

    os.environ["DOCFLOW_LOG_DIR"] = str(logs)
    marker = root / "crash_marker.json"

    def fake_scan_document(*, task_id: str, settings: ScannerSettings, operation_id: str) -> Path:
        del task_id, operation_id
        source = settings.incoming_dir / "PF_ACCEPTANCE_SCENARIO_10.pdf"
        create_scan_pdf(source)
        return source

    document_flow.scan_document = fake_scan_document

    if args.stage == "after_temp_copy":
        original = storage_module.copy_file_to_temp

        def crash_after_temp(source_path: Path, temp_path: Path, *, buffer_size: int) -> None:
            original(source_path, temp_path, buffer_size=buffer_size)
            write_marker(marker, stage=args.stage, source=str(source_path), temp=str(temp_path))
            os._exit(90)

        storage_module.copy_file_to_temp = crash_after_temp

    elif args.stage == "during_copy":
        def crash_during_copy(fsrc, fdst, length=0):
            chunk = fsrc.read(min(length or 65536, 65536))
            fdst.write(chunk)
            fdst.flush()
            os.fsync(fdst.fileno())
            write_marker(marker, stage=args.stage, bytes_copied=len(chunk))
            os._exit(91)

        storage_module.shutil.copyfileobj = crash_during_copy

    elif args.stage == "after_publish":
        original_finalize = storage_module.finalize_atomic_move

        def crash_after_publish(temp_path: Path, destination_path: Path) -> None:
            original_finalize(temp_path, destination_path)
            write_marker(
                marker,
                stage=args.stage,
                temp=str(temp_path),
                destination=str(destination_path),
            )
            os._exit(92)

        storage_module.finalize_atomic_move = crash_after_publish

    elif args.stage != "retry":
        raise ValueError(f"Unknown stage: {args.stage}")

    result = document_flow.process_document_scan(
        task_id=f"ACC-010-{args.case_id}",
        doc_type="НКЛ",
        document_datetime="2026-07-16T12:40:00",
        document_number=f"010-{args.case_id}",
        scanner_settings=ScannerSettings(incoming_dir=incoming, min_pdf_size_bytes=100),
        storage_settings=StorageSettings(archive_root=archive),
        lock_settings=ScannerLockSettings(stale_after_seconds=0),
        idempotency_key=f"acceptance-scenario-10-{args.case_id}",
        idempotency_settings=IdempotencySettings(
            record_dir=records,
            in_progress_stale_after_seconds=0,
        ),
    )
    write_marker(
        root / "retry_result.json",
        stage=args.stage,
        file_name=result.file_name,
        file_path=str(result.file_path),
        idempotent_replay=result.idempotent_replay,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=["after_temp_copy", "during_copy", "after_publish", "retry"],
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
