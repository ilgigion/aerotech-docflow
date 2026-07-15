from pathlib import Path
from types import SimpleNamespace
import builtins
import subprocess
import tempfile

from pypdf import PdfWriter

import app.scanner as scanner_module
from app.locks import ScannerFileLock
from app.scanner import (
    ScannerOutputInvalidError,
    ScannerProcessStillRunningError,
    ScannerSettings,
    kill_process_tree,
    run_naps2,
    validate_pdf_output,
)
from app.storage import FileMoveError, finalize_atomic_move


def write_valid_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    existing = root / "existing.pdf"
    temp = root / "existing.tmp"
    existing.write_bytes(b"ORIGINAL")
    temp.write_bytes(b"REPLACEMENT")

    try:
        finalize_atomic_move(temp, existing)
        raise AssertionError("Expected no-clobber FileMoveError")
    except FileMoveError as exc:
        assert exc.code == "destination_appeared_during_atomic_move"

    assert existing.read_bytes() == b"ORIGINAL"
    assert temp.read_bytes() == b"REPLACEMENT"

    published = root / "published.pdf"
    published_temp = root / "published.tmp"
    published_temp.write_bytes(b"PUBLISHED")
    finalize_atomic_move(published_temp, published)
    assert published.read_bytes() == b"PUBLISHED"
    assert not published_temp.exists()

    settings = ScannerSettings(
        min_pdf_size_bytes=20,
        stable_checks=1,
        stable_interval_seconds=0.001,
    )

    valid_pdf = root / "valid.pdf"
    write_valid_pdf(valid_pdf)
    validate_pdf_output(valid_pdf, settings)

    corrupt_pdf = root / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.7\n" + b"garbage" * 30 + b"\n%%EOF\n")
    try:
        validate_pdf_output(corrupt_pdf, settings)
        raise AssertionError("Expected corrupt PDF rejection")
    except ScannerOutputInvalidError as exc:
        assert exc.code == "output_pdf_parse_error"

    missing_eof = root / "missing-eof.pdf"
    missing_eof.write_bytes(b"%PDF-1.7\n" + b"x" * 100)
    try:
        validate_pdf_output(missing_eof, settings)
        raise AssertionError("Expected missing EOF rejection")
    except ScannerOutputInvalidError as exc:
        assert exc.code == "output_pdf_missing_eof"

    original_import = builtins.__import__

    def import_without_pypdf(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("simulated missing pypdf")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = import_without_pypdf
    try:
        try:
            validate_pdf_output(valid_pdf, settings)
            raise AssertionError("Expected missing pypdf rejection")
        except ScannerOutputInvalidError as exc:
            assert exc.code == "pypdf_not_installed"
    finally:
        builtins.__import__ = original_import

    lock_path = root / ".scanner.lock"
    lock = ScannerFileLock(lock_path, "OP", "TASK")
    lock.acquire()
    still_running_error = ScannerProcessStillRunningError(
        code="scanner_process_still_running",
        operator_message="manual recovery",
    )
    lock.__exit__(type(still_running_error), still_running_error, None)
    assert lock_path.exists()


class FakeProcess:
    pid = 12345

    def __init__(self):
        self.alive = True
        self.kill_called = False

    def poll(self):
        return None if self.alive else -9

    def kill(self):
        self.kill_called = True
        self.alive = False


fake_process = FakeProcess()
original_run = scanner_module.subprocess.run
original_os_name = scanner_module.os.name
scanner_module.os.name = "nt"
scanner_module.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
    returncode=1,
    stdout="",
    stderr="access denied",
)
try:
    kill_process_tree(fake_process, operation_id="UNIT_KILL")
finally:
    scanner_module.subprocess.run = original_run
    scanner_module.os.name = original_os_name

assert fake_process.kill_called
assert fake_process.poll() is not None


class UnkillableProcess:
    pid = 54321
    returncode = None

    def __init__(self):
        self.communicate_calls = 0

    def poll(self):
        return None

    def kill(self):
        return None

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd="NAPS2", timeout=timeout)
        return "", ""


unkillable = UnkillableProcess()
original_popen = scanner_module.subprocess.Popen
original_run = scanner_module.subprocess.run
original_os_name = scanner_module.os.name
scanner_module.os.name = "nt"
scanner_module.subprocess.Popen = lambda *args, **kwargs: unkillable
scanner_module.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
    returncode=1,
    stdout="",
    stderr="access denied",
)
try:
    try:
        run_naps2(
            command=["NAPS2.Console.exe"],
            settings=ScannerSettings(
                timeout_seconds=1,
                timeout_kill_grace_seconds=1,
                verify_process_exit_seconds=0,
            ),
            output_path=Path("missing-audit-output.pdf"),
            operation_id="UNIT_UNKILLABLE",
        )
        raise AssertionError("Expected ScannerProcessStillRunningError")
    except ScannerProcessStillRunningError as exc:
        assert exc.code == "scanner_process_still_running"
        assert exc.preserve_scanner_lock is True
finally:
    scanner_module.subprocess.Popen = original_popen
    scanner_module.subprocess.run = original_run
    scanner_module.os.name = original_os_name

print("OK: critical storage/scanner/PDF safety")
