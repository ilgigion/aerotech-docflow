from datetime import datetime
from pathlib import Path
import logging
import shutil

from app.storage import StorageError, StorageSettings, store_document


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


source_path = Path(r"D:\incoming\ATOMIC_STORAGE_FAILURE_SOURCE.pdf")
archive_root = Path(r"D:\archive_atomic_failure_test")

source_path.parent.mkdir(parents=True, exist_ok=True)

if archive_root.exists():
    if archive_root.is_dir():
        shutil.rmtree(archive_root)
    else:
        archive_root.unlink()

# Создаём файл вместо папки archive_root, чтобы искусственно вызвать ошибку архива.
archive_root.write_text("not a directory", encoding="utf-8")

source_path.write_bytes(
    b"%PDF-1.4\n"
    b"% atomic failure test\n"
    b"%%EOF\n"
)

settings = StorageSettings(
    archive_root=archive_root,
    keep_temp_on_error=False,
)


try:
    store_document(
        source_path=source_path,
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        settings=settings,
        operation_id="ATOMIC_FAILURE_TEST",
    )

    print("ОШИБКА: ожидалась StorageError, но перенос прошёл")

except StorageError as exc:
    print()
    print("OK: получили ожидаемую ошибку")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

    print()
    print(f"source still exists: {source_path.exists()}")
    assert source_path.exists(), "при ошибке архива исходный временный PDF должен остаться"

    print("ALL OK")
