from datetime import datetime
from pathlib import Path
import logging
import shutil

from app.naming import NamingError
from app.storage import StorageError, StorageSettings, store_document


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


source_path = Path(r"D:\incoming\ATOMIC_STORAGE_TEST_SOURCE.pdf")
archive_root = Path(r"D:\archive_atomic_test")

source_path.parent.mkdir(parents=True, exist_ok=True)

if archive_root.exists():
    shutil.rmtree(archive_root)

settings = StorageSettings(
    archive_root=archive_root,
    keep_temp_on_error=False,
)


def create_test_pdf(path: Path, marker: str) -> int:
    content = (
        b"%PDF-1.4\n"
        + f"% atomic storage test {marker}\n".encode("utf-8")
        + b"1 0 obj\n<<>>\nendobj\n"
        + b"%%EOF\n"
    )
    path.write_bytes(content)
    return len(content)


try:
    print()
    print("TEST 1: первый перенос")

    source_size_1 = create_test_pdf(source_path, "first")

    result_1 = store_document(
        source_path=source_path,
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        settings=settings,
        operation_id="ATOMIC_TEST_001",
    )

    print("OK")
    print(f"Имя файла: {result_1.file_name}")
    print(f"Путь файла: {result_1.file_path}")
    print(f"source exists after move: {source_path.exists()}")
    print(f"destination size: {result_1.file_path.stat().st_size}")
    print(f"source expected size: {source_size_1}")

    assert not source_path.exists(), "source_path должен быть удалён после успешного переноса"
    assert result_1.file_path.exists(), "финальный файл должен существовать"
    assert result_1.file_path.stat().st_size == source_size_1, "размер финального файла должен совпадать"

    tmp_files_after_first = list(result_1.file_path.parent.glob("*.tmp"))
    print(f"tmp files after first move: {tmp_files_after_first}")
    assert not tmp_files_after_first, "после успешного переноса .tmp файлов быть не должно"

    print()
    print("TEST 2: дубль должен получить _01")

    source_size_2 = create_test_pdf(source_path, "second")

    result_2 = store_document(
        source_path=source_path,
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
        settings=settings,
        operation_id="ATOMIC_TEST_002",
    )

    print("OK")
    print(f"Имя файла: {result_2.file_name}")
    print(f"Путь файла: {result_2.file_path}")
    print(f"source exists after move: {source_path.exists()}")

    assert result_2.file_name.endswith("_01.pdf"), "дубль должен получить суффикс _01.pdf"
    assert not source_path.exists(), "source_path должен быть удалён после успешного переноса"
    assert result_2.file_path.exists(), "финальный файл-дубль должен существовать"
    assert result_2.file_path.stat().st_size == source_size_2, "размер второго финального файла должен совпадать"

    tmp_files_after_second = list(result_2.file_path.parent.glob("*.tmp"))
    print(f"tmp files after second move: {tmp_files_after_second}")
    assert not tmp_files_after_second, "после второго переноса .tmp файлов быть не должно"

    print()
    print("ALL OK")

except NamingError as exc:
    print()
    print("ОШИБКА ФОРМИРОВАНИЯ ИМЕНИ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())

except StorageError as exc:
    print()
    print("ОШИБКА STORAGE")
    print(exc.to_operator_text())
    print(exc.to_log_dict())
