from datetime import datetime
from pathlib import Path
import logging

from app.document_flow import retry_store_existing_scan
from app.storage import StorageError, StorageSettings, store_document


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


source_path = Path(r"D:\incoming\RETRY_TEST_SOURCE.pdf")
bad_archive_root = Path(r"D:\archive_root_as_file_for_retry_test")
good_archive_root = Path(r"D:\archive_test")

# Готовим временный PDF, как будто scanner.py уже успешно отсканировал документ.
source_path.parent.mkdir(parents=True, exist_ok=True)
source_path.write_bytes(b"%PDF-1.4\n% retry test pdf\n")

# Создаём ошибочный archive_root: это файл, а не папка.
# Так мы имитируем ситуацию: скан готов, но архив недоступен/настроен неправильно.
if bad_archive_root.exists():
    if bad_archive_root.is_dir():
        raise RuntimeError(f"Для теста {bad_archive_root} должен быть файлом, а не папкой")
else:
    bad_archive_root.write_text("not a directory", encoding="utf-8")

print()
print("STEP 1: пробуем сохранить в неправильный архив")

try:
    store_document(
        source_path=source_path,
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        settings=StorageSettings(archive_root=bad_archive_root),
        operation_id="RETRY_TEST_BAD_STORAGE",
    )

    print("ОШИБКА: сохранение не должно было пройти")

except StorageError as exc:
    print("OK: получили ошибку архива")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

print()
print("STEP 2: проверяем, что временный PDF остался на месте")
print(f"source_path exists: {source_path.exists()}")

if not source_path.exists():
    raise RuntimeError("Временный PDF исчез, повторный перенос невозможен")

print()
print("STEP 3: повторяем только перенос в правильный архив без нового сканирования")

try:
    result = retry_store_existing_scan(
        task_id="TEST_RETRY_STORAGE",
        source_path=source_path,
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        storage_settings=StorageSettings(archive_root=good_archive_root),
    )

    print()
    print("OK")
    print(f"Operation ID: {result.operation_id}")
    print(f"Исходный временный файл: {result.source_path}")
    print(f"Имя файла: {result.file_name}")
    print(f"Финальный путь: {result.file_path}")
    print(f"source_path exists after move: {source_path.exists()}")

except StorageError as exc:
    print()
    print("ОШИБКА ПОВТОРНОГО ПЕРЕНОСА")
    print(exc.to_operator_text())
    print(exc.to_log_dict())
