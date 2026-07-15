from datetime import datetime
from pathlib import Path
import logging
import shutil

from app.storage import StorageSettings, store_document


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

archive_root = Path(r"D:\archive_reservation_test")
incoming_dir = Path(r"D:\incoming")
source_path_1 = incoming_dir / "RESERVATION_TEST_SOURCE_1.pdf"
source_path_2 = incoming_dir / "RESERVATION_TEST_SOURCE_2.pdf"

if archive_root.exists():
    shutil.rmtree(archive_root)

incoming_dir.mkdir(parents=True, exist_ok=True)
source_path_1.write_bytes(b"%PDF-1.4\n% reservation test 1\n%%EOF\n")
source_path_2.write_bytes(b"%PDF-1.4\n% reservation test 2\n%%EOF\n")

settings = StorageSettings(
    archive_root=archive_root,
    keep_temp_on_error=False,
    reservation_stale_after_seconds=30 * 60,
)

print()
print("TEST 1: первый перенос получает базовое имя")

result_1 = store_document(
    source_path=source_path_1,
    doc_type="УПД",
    document_datetime=datetime(2026, 7, 10, 10, 10, 25),
    document_number="2455B",
    settings=settings,
    operation_id="RESERVATION_TEST_001",
)

print("OK")
print(result_1.file_name)
print(result_1.file_path)

print()
print("TEST 2: второй перенос получает _01")

result_2 = store_document(
    source_path=source_path_2,
    doc_type="УПД",
    document_datetime=datetime(2026, 7, 10, 10, 10, 25),
    document_number="2455B",
    settings=settings,
    operation_id="RESERVATION_TEST_002",
)

print("OK")
print(result_2.file_name)
print(result_2.file_path)

reserve_files = list((archive_root / "2026" / "УПД").glob("*.reserve"))
tmp_files = list((archive_root / "2026" / "УПД").glob("*.tmp"))

print()
print(f"reserve files after success: {reserve_files}")
print(f"tmp files after success: {tmp_files}")

assert result_1.file_name == "УПД_260710_101025_2455B.pdf"
assert result_2.file_name == "УПД_260710_101025_2455B_01.pdf"
assert not source_path_1.exists()
assert not source_path_2.exists()
assert not reserve_files
assert not tmp_files

print()
print("ALL OK")
