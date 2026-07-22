import subprocess
import sys

MODULES = [
    "tests.unit.run_configuration_test",
    "tests.unit.run_naming_test",
    "tests.unit.run_storage_test",
    "tests.unit.run_storage_failure_test",
    "tests.unit.run_idempotency_test",
    "tests.unit.run_idempotency_path_safety_test",
    "tests.unit.run_publish_recovery_test",
    "tests.unit.run_operation_id_correlation_test",
    "tests.unit.run_scan_start_time_test",
    "tests.unit.run_acceptance_runner_test",
    "tests.unit.run_critical_safety_test",
    "tests.unit.run_archive_hardening_test",
    "tests.unit.run_monthly_file_logging_test",
    "tests.unit.run_incoming_cleanup_test",
    "tests.unit.run_api_test",
]

for module in MODULES:
    print(f"\n=== {module} ===")
    completed = subprocess.run([sys.executable, "-m", module])
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

print("\nALL UNIT TESTS OK")
