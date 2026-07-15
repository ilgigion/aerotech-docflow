from pathlib import Path
import os
import tempfile
import time

from app.incoming_cleanup import IncomingCleanupSettings, cleanup_incoming_folder

with tempfile.TemporaryDirectory() as tmp:
    incoming = Path(tmp) / "incoming"
    incoming.mkdir()
    old_pdf = incoming / "PF_OLD.pdf"
    new_pdf = incoming / "PF_NEW.pdf"
    manual_pdf = incoming / "manual.pdf"

    for p in [old_pdf, new_pdf, manual_pdf]:
        p.write_bytes(b"%PDF-1.4\ncleanup\n%%EOF\n")

    old_time = time.time() - 48 * 60 * 60
    os.utime(old_pdf, (old_time, old_time))

    settings = IncomingCleanupSettings(incoming_dir=incoming, min_age_seconds=24 * 60 * 60)
    dry = cleanup_incoming_folder(settings=settings, action="dry_run")
    assert dry.candidate_count == 1
    assert dry.candidates[0].path == old_pdf

    result = cleanup_incoming_folder(settings=settings, action="quarantine")
    assert result.quarantined_count == 1
    assert not old_pdf.exists()
    assert new_pdf.exists()
    assert manual_pdf.exists()

print("OK: incoming cleanup")
