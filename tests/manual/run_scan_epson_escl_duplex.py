"""Legacy direct-mode entry point; direct scanner settings come from TOML."""

from __future__ import annotations

import argparse
import os

from app.configuration import apply_configuration
from app.document_flow import process_document_scan


parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--task-id", required=True)
parser.add_argument("--doc-type", required=True)
parser.add_argument("--document-number", required=True)
parser.add_argument("--idempotency-key")
args = parser.parse_args()

apply_configuration(args.config)
if os.getenv("NAPS2_PROFILE", "").strip():
    raise SystemExit(
        "This direct-mode check requires scanner.profile = \"\" in config.toml"
    )

result = process_document_scan(
    task_id=args.task_id,
    doc_type=args.doc_type,
    document_number=args.document_number,
    idempotency_key=args.idempotency_key,
)
print("OK")
print(f"Operation ID: {result.operation_id}")
print(f"Task ID: {result.task_id}")
print(f"Имя файла: {result.file_name}")
print(f"Финальный путь: {result.file_path}")
