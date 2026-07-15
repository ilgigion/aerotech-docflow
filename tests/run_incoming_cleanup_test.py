from pathlib import Path
import logging
import os
import shutil
import time

from app.incoming_cleanup import IncomingCleanupSettings, cleanup_incoming_folder


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


incoming_dir = Path(r"D:\incoming_cleanup_test")

if incoming_dir.exists():
    shutil.rmtree(incoming_dir)

incoming_dir.mkdir(parents=True, exist_ok=True)


def write_pdf(path: Path, text: str) -> None:
    path.write_bytes(
        b"%PDF-1.4\n"
        + f"% {text}\n".encode("utf-8")
        + b"%%EOF\n"
    )


old_pf_1 = incoming_dir / "PF_OLD_001.pdf"
old_pf_2 = incoming_dir / "PF_OLD_002.pdf"
new_pf = incoming_dir / "PF_NEW_001.pdf"
manual_file = incoming_dir / "MANUAL_SCAN.pdf"
text_file = incoming_dir / "PF_NOT_PDF.txt"
lock_file = incoming_dir / ".scanner.lock"

write_pdf(old_pf_1, "old 1")
write_pdf(old_pf_2, "old 2")
write_pdf(new_pf, "new")
write_pdf(manual_file, "manual")
text_file.write_text("not pdf", encoding="utf-8")

# Делаем два PF-файла старыми.
old_time = time.time() - 48 * 60 * 60
os.utime(old_pf_1, (old_time, old_time))
os.utime(old_pf_2, (old_time, old_time))

settings = IncomingCleanupSettings(
    incoming_dir=incoming_dir,
    min_age_seconds=24 * 60 * 60,
    lock_file=lock_file,
    skip_if_lock_exists=True,
    stable_checks=1,
    stable_interval_seconds=0.05,
)

print()
print("TEST 1: dry_run должен найти только старые PF_*.pdf")

result_dry = cleanup_incoming_folder(
    settings=settings,
    action="dry_run",
)

print(f"skipped: {result_dry.skipped}")
print(f"candidates: {result_dry.candidate_count}")
for candidate in result_dry.candidates:
    print(f"- {candidate.path.name}, age_seconds={int(candidate.age_seconds)}")

assert result_dry.candidate_count == 2
assert old_pf_1.exists()
assert old_pf_2.exists()
assert new_pf.exists()
assert manual_file.exists()
assert text_file.exists()

print()
print("TEST 2: quarantine должен перенести только старые PF_*.pdf")

result_move = cleanup_incoming_folder(
    settings=settings,
    action="quarantine",
)

print(f"quarantined: {result_move.quarantined_count}")
print(f"errors: {result_move.error_count}")
print(f"quarantine_dir: {result_move.quarantine_dir}")
for item in result_move.quarantined_files:
    print(f"- {item.source_path.name} -> {item.destination_path}")

assert result_move.quarantined_count == 2
assert not old_pf_1.exists()
assert not old_pf_2.exists()
assert new_pf.exists()
assert manual_file.exists()
assert text_file.exists()
assert result_move.quarantine_dir.exists()

print()
print("TEST 3: если есть scanner.lock, cleanup должен пропуститься")

# Создаём ещё один старый PF, но включаем lock.
old_pf_3 = incoming_dir / "PF_OLD_003.pdf"
write_pdf(old_pf_3, "old 3")
os.utime(old_pf_3, (old_time, old_time))
lock_file.write_text("locked", encoding="utf-8")

result_locked = cleanup_incoming_folder(
    settings=settings,
    action="quarantine",
)

print(f"skipped: {result_locked.skipped}")
print(f"skipped_reason: {result_locked.skipped_reason}")

assert result_locked.skipped is True
assert old_pf_3.exists()

print()
print("ALL OK")
