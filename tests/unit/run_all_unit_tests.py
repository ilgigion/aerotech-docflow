import subprocess
import sys

MODULES = [
    "tests.unit.run_naming_test",
    "tests.unit.run_storage_test",
    "tests.unit.run_storage_failure_test",
    "tests.unit.run_idempotency_test",
    "tests.unit.run_monthly_file_logging_test",
    "tests.unit.run_incoming_cleanup_test",
]

for module in MODULES:
    print(f"\n=== {module} ===")
    completed = subprocess.run([sys.executable, "-m", module])
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

print("\nALL UNIT TESTS OK")
