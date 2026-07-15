from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
import shutil
import tempfile

from app.monthly_file_logging import configure_monthly_file_logging, monthly_log_file_path


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="docflow_monthly_log_test_"))
    try:
        log_dir = root / "logs"
        log_path = configure_monthly_file_logging(log_dir=log_dir)

        logger = logging.getLogger("app.monthly_log_test")
        logger.info("monthly logging test message operation_id=%s", "TEST_LOG")

        expected_path = monthly_log_file_path(log_dir, at=datetime.now())
        assert log_path == expected_path
        assert expected_path.exists(), f"log file was not created: {expected_path}"

        text = expected_path.read_text(encoding="utf-8")
        assert "monthly logging test message" in text
        assert "TEST_LOG" in text

        print("OK")
        print("Monthly file logging test passed")
        print(f"log_path: {expected_path}")

    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
