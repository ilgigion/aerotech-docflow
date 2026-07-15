from datetime import datetime
from pathlib import Path
import json
import logging
import shutil

from app.storage import StorageSettings, build_reservation_path, store_document


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

archive_root = Path(r"D:\archive_reservation_collision_test")
incoming_dir = Path(r"D:\incoming")
source_path = incoming_dir / "RESERVATION_COLLISION_SOURCE.pdf"

if archive_root.exists():
    shutil.rmtree(archive_root)

incoming_dir.mkdir(parents=True, exist_ok=True)
source_path.write_bytes(b"%PDF-1.4\n% reservation collision test\n%%EOF\n")

destination_dir = archive_root / "2026" / "УПД"
destination_dir.mkdir(parents=True, exist_ok=True)

base_destination = destination_dir / "УПД_260710_101025_2455B.pdf"
reservation_path = build_reservation_path(base_destination)
reservation_path.write_text(
    json.dumps(
        {
            "operation_id": "OTHER_RUNNING_OPERATION",
            "destination_path": str(base_destination),
            "pid": 999999,
            "hostname": "TEST",
            "created_at_utc": "2999-01-01T00:00:00+00:00",
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

settings = StorageSettings(
    archive_root=archive_root,
    reservation_stale_after_seconds=30 * 60,
)

print()
print("TEST: базовое имя занято .reserve, значит должен быть выбран _01")

result = store_document(
    source_path=source_path,
    doc_type="УПД",
    document_datetime=datetime(2026, 7, 10, 10, 10, 25),
    document_number="2455B",
    settings=settings,
    operation_id="RESERVATION_COLLISION_TEST",
)

print("OK")
print(result.file_name)
print(result.file_path)

assert result.file_name == "УПД_260710_101025_2455B_01.pdf"
assert reservation_path.exists(), "чужой активный reserve не должен быть удалён"
assert result.file_path.exists()
assert not source_path.exists()

print()
print("ALL OK")
