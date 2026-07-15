from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

from app.locks import ScannerLockSettings, scanner_lock
from app.scanner import ScannerSettings, ScannerTimeoutError, run_naps2
from app.scanner_recovery import diagnose_scanner_state


def write_fake_hanging_scanner_script(path: Path) -> None:
    path.write_text(
        """
from pathlib import Path
import sys
import time

output_path = Path(sys.argv[1])
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes(b'%PDF-1.4\\n% fake partial pdf created before hang\\n')
time.sleep(60)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_timeout_quarantines_untrusted_output() -> None:
    root = Path(tempfile.mkdtemp(prefix="docflow_timeout_test_"))
    try:
        incoming = root / "incoming"
        incoming.mkdir()
        output_path = incoming / "PF_TIMEOUT_TEST.pdf"
        fake_script = root / "fake_hanging_scanner.py"
        write_fake_hanging_scanner_script(fake_script)

        settings = ScannerSettings(
            naps2_executable=Path(sys.executable),
            incoming_dir=incoming,
            profile_name=None,
            driver="test",
            device_name="test",
            timeout_seconds=2,
            timeout_kill_grace_seconds=1,
            verify_process_exit_seconds=3,
            quarantine_failed_scan_outputs=True,
        )

        try:
            run_naps2(
                command=[sys.executable, str(fake_script), str(output_path)],
                settings=settings,
                output_path=output_path,
                operation_id="TEST_TIMEOUT",
            )
        except ScannerTimeoutError as exc:
            assert exc.code == "scanner_timeout"
            assert "quarantine_path=" in exc.technical_message
        else:
            raise AssertionError("ScannerTimeoutError was not raised")

        assert not output_path.exists(), "partial output must be moved from incoming"
        quarantined = list((incoming / "_failed_runtime").rglob("PF_TIMEOUT_TEST.pdf"))
        assert len(quarantined) == 1, f"expected one quarantined file, got {quarantined}"

        report = diagnose_scanner_state(incoming, root / "archive")
        assert report.lock_exists is False
        assert report.archive_tmp_files == []
        assert report.archive_reserve_files == []

    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stale_lock_auto_takeover() -> None:
    root = Path(tempfile.mkdtemp(prefix="docflow_stale_lock_test_"))
    try:
        incoming = root / "incoming"
        incoming.mkdir()
        lock_path = incoming / ".scanner.lock"

        stale_time = datetime.now(timezone.utc) - timedelta(hours=3)
        lock_path.write_text(
            json.dumps(
                {
                    "operation_id": "OLD_OPERATION",
                    "task_id": "OLD_TASK",
                    "pid": 99999999,
                    "hostname": "host-that-is-not-this-process",
                    "created_at_utc": stale_time.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        with scanner_lock(
            lock_path=lock_path,
            operation_id="NEW_OPERATION",
            task_id="NEW_TASK",
            settings=ScannerLockSettings(
                stale_after_seconds=1,
                wait_timeout_seconds=0,
                allow_stale_takeover=True,
            ),
        ):
            current = json.loads(lock_path.read_text(encoding="utf-8"))
            assert current["operation_id"] == "NEW_OPERATION"

        assert not lock_path.exists(), "lock must be released after context exit"

    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    test_timeout_quarantines_untrusted_output()
    test_stale_lock_auto_takeover()
    print("OK")
    print("External failure protections unit test passed")


if __name__ == "__main__":
    main()
