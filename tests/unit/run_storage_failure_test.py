from datetime import datetime
from pathlib import Path
import tempfile

from app.storage import StorageError, StorageSettings, store_document

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    incoming = root / "incoming"
    incoming.mkdir()
    source = incoming / "source.pdf"
    source.write_bytes(b"%PDF-1.4\nunit failure\n%%EOF\n")

    bad_archive = root / "archive_as_file"
    bad_archive.write_text("not a directory", encoding="utf-8")

    try:
        store_document(source, "УПД", datetime(2026, 7, 10, 10, 10, 25), "2455B", settings=StorageSettings(archive_root=bad_archive), operation_id="UNIT_STORAGE_FAIL")
        raise AssertionError("Expected StorageError")
    except StorageError:
        assert source.exists()

print("OK: storage failure keeps source")
