from datetime import datetime
from pathlib import Path
import shutil

from app.naming import NamingError
from app.storage import StorageError, StorageSettings, store_document


source_path = Path(r"D:\incoming\STORAGE_TEST_SOURCE.pdf")
archive_root = Path(r"D:\archive_test")

# Готовим тестовый временный PDF.
source_path.parent.mkdir(parents=True, exist_ok=True)
source_path.write_bytes(b"%PDF-1.4\n% test pdf\n")

# Для чистого теста можно удалить тестовый архив.
# Если не хочешь удалять старые файлы, закомментируй эти строки.
if archive_root.exists():
    shutil.rmtree(archive_root)

settings = StorageSettings(
    archive_root=archive_root,
)


try:
    result = store_document(
        source_path=source_path,
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        settings=settings,
    )

    print()
    print("OK")
    print(f"Имя файла: {result.file_name}")
    print(f"Путь файла: {result.file_path}")

except NamingError as exc:
    print()
    print("ОШИБКА ФОРМИРОВАНИЯ ИМЕНИ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

except StorageError as exc:
    print()
    print("ОШИБКА ПЕРЕНОСА В АРХИВ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())