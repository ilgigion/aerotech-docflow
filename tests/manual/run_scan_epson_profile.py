"""Legacy manual entry point; all scanner and archive settings come from TOML."""

from __future__ import annotations

import argparse
import logging

from app.configuration import apply_configuration
from app.document_flow import process_document_scan
from app.locks import ScannerLockError
from app.naming import NamingError
from app.scanner import ScannerError
from app.storage import StorageError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--task-id", required=True)
parser.add_argument("--doc-type", required=True)
parser.add_argument("--document-number", required=True)
parser.add_argument("--scanner-profile")
parser.add_argument("--idempotency-key")
args = parser.parse_args()

apply_configuration(args.config)

try:
    result = process_document_scan(
        task_id=args.task_id,
        doc_type=args.doc_type,
        document_number=args.document_number,
        scanner_profile=args.scanner_profile,
        idempotency_key=args.idempotency_key,
    )
    print("OK")
    print(f"Operation ID: {result.operation_id}")
    print(f"Task ID: {result.task_id}")
    print(f"Имя файла: {result.file_name}")
    print(f"Финальный путь: {result.file_path}")
except ScannerLockError as exc:
    print("СКАНЕР ЗАНЯТ", exc.to_operator_text(), exc.to_log_dict(), sep="\n")
except ScannerError as exc:
    print("ОШИБКА СКАНИРОВАНИЯ", exc.to_operator_text(), exc.to_log_dict(), sep="\n")
except NamingError as exc:
    print("ОШИБКА ФОРМИРОВАНИЯ ИМЕНИ", exc.to_operator_text(), exc.to_log_dict(), sep="\n")
except StorageError as exc:
    print("ОШИБКА СОХРАНЕНИЯ В АРХИВ", exc.to_operator_text(), exc.to_log_dict(), sep="\n")
