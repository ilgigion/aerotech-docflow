from datetime import datetime
from pathlib import Path
import logging

from app.document_flow import process_document_scan
from app.locks import ScannerLockError, ScannerLockSettings
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

    # Прямой режим без профиля.
    # Двустороннее сканирование задаётся через --source duplex.
    profile_name=None,
    driver="escl",
    device_name="EPSON DS-790WN",
    source="duplex",
    dpi=300,
    page_size="a4",
    bit_depth="gray",

    timeout_seconds=300,
)


storage_settings = StorageSettings(
    archive_root=Path(r"D:\archive_test"),
)


lock_settings = ScannerLockSettings(
    lock_file=None,
    stale_after_seconds=30 * 60,
    wait_timeout_seconds=0,
    retry_interval_seconds=0.5,
    allow_stale_takeover=True,
)


try:
    result = process_document_scan(
        task_id="TEST_EPSON_ESCL_DUPLEX",
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        scanner_settings=scanner_settings,
        storage_settings=storage_settings,
        lock_settings=lock_settings,
        use_lock=True,
    )

    print()
    print("OK")
    print(f"Operation ID: {result.operation_id}")
    print(f"Task ID: {result.task_id}")
    print(f"Имя файла: {result.file_name}")
    print(f"Финальный путь: {result.file_path}")

except ScannerLockError as exc:
    print()
    print("СКАНЕР ЗАНЯТ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

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
