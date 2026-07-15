from datetime import datetime
from pathlib import Path
import tempfile

from app.storage import StorageSettings, store_document

def fake_pdf(path: Path, marker: str) -> None:
    path.write_bytes(b"%PDF-1.4\n" + marker.encode("utf-8") + b"\n%%EOF\n")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    incoming = root / "incoming"
    archive = root / "archive"
    incoming.mkdir()

    settings = StorageSettings(archive_root=archive)

    source1 = incoming / "source1.pdf"
    source2 = incoming / "source2.pdf"
    fake_pdf(source1, "one")
    fake_pdf(source2, "two")

    result1 = store_document(source1, "УПД", datetime(2026, 7, 10, 10, 10, 25), "2455B", settings=settings, operation_id="UNIT_STORAGE_1")
    result2 = store_document(source2, "УПД", datetime(2026, 7, 10, 10, 10, 25), "2455B", settings=settings, operation_id="UNIT_STORAGE_2")

    assert result1.file_name == "УПД_260710_101025_2455B.pdf"
    assert result2.file_name == "УПД_260710_101025_2455B_01.pdf"
    assert result1.file_path.exists()
    assert result2.file_path.exists()
    assert not source1.exists()
    assert not source2.exists()
    assert not list(archive.rglob("*.tmp"))
    assert not list(archive.rglob("*.reserve"))

print("OK: storage")
