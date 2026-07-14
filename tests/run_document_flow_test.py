from datetime import datetime
from pathlib import Path
import logging

from app.document_flow import process_document_scan, process_document_scan_safe
from app.naming import NamingError
from app.scanner import ScannerError, ScannerSettings
from app.storage import StorageError, StorageSettings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

scanner_settings = ScannerSettings(
    naps2_executable=Path(r"C:\Program Files\NAPS2\NAPS2.Console.exe"),
    incoming_dir=Path(r"D:\incoming"),
    profile_name=None,
    driver="twain",
    device_name="Canon G600 series Network",
    source=None,
    dpi=None,
    page_size=None,
    bit_depth=None,
    timeout_seconds=120,
)

storage_settings = StorageSettings(
    archive_root=Path(r"D:\archive_test"),
)

# Вариант 1: старый режим с исключениями.
try:
    result = process_document_scan(
        task_id="TEST_005",
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        scanner_settings=scanner_settings,
        storage_settings=storage_settings,
    )

    print()
    print("OK")
    print(f"Operation ID: {result.operation_id}")
    print(f"Task ID: {result.task_id}")
    print(f"Временный путь: {result.temp_scan_path}")
    print(f"Имя файла: {result.file_name}")
    print(f"Финальный путь: {result.file_path}")

except ScannerError as exc:
    print()
    print("ОШИБКА СКАНИРОВАНИЯ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

except NamingError as exc:
    print()
    print("ОШИБКА ФОРМИРОВАНИЯ ИМЕНИ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

except StorageError as exc:
    print()
    print("ОШИБКА СОХРАНЕНИЯ В АРХИВ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

# Вариант 2: безопасный формат для будущего API.
# Пока закомментирован, потому что он тоже запустит реальное сканирование.
# safe_result = process_document_scan_safe(
#     task_id="TEST_006",
#     doc_type="УПД",
#     document_datetime="2026-07-10 10:10:25",
#     document_number="2455B",
#     scanner_settings=scanner_settings,
#     storage_settings=storage_settings,
# )
# print(safe_result.to_dict())
