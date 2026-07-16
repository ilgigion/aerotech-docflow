from datetime import datetime
from pathlib import Path
import logging
import tempfile

from app.monthly_file_logging import (
    close_monthly_file_logging,
    configure_monthly_file_logging,
    monthly_log_file_path,
)

with tempfile.TemporaryDirectory() as tmp:
    log_dir = Path(tmp) / "logs"
    path = monthly_log_file_path(log_dir, at=datetime(2026, 7, 15), file_prefix="docflow")
    assert path.name == "docflow_2026_07.txt"

    configured = configure_monthly_file_logging(log_dir=log_dir, level=logging.INFO)
    logging.getLogger("unit.monthly").info("monthly logging works")

    assert configured.parent == log_dir
    assert configured.exists()
    assert "monthly logging works" in configured.read_text(encoding="utf-8")

    closed_count = close_monthly_file_logging(log_dir=log_dir, file_prefix="docflow")
    assert closed_count == 1

    expired = log_dir / "docflow_2000_01.txt"
    expired.write_text("expired", encoding="utf-8")
    configured = configure_monthly_file_logging(
        log_dir=log_dir,
        level=logging.INFO,
        max_bytes=80,
        backup_count=2,
        retention_months=12,
    )
    logging.getLogger("unit.monthly").info("X" * 200)
    assert configured.exists()
    assert configured.with_name(f"{configured.name}.1").exists()
    assert not expired.exists()
    close_monthly_file_logging(log_dir=log_dir, file_prefix="docflow")

print("OK: monthly logging")
