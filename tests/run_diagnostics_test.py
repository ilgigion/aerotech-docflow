from pathlib import Path

from app.scanner import ScannerSettings, check_scanner_environment
from app.storage import StorageSettings, check_storage_environment


scanner_settings = ScannerSettings(
    naps2_executable=Path(r"C:\Program Files\NAPS2\NAPS2.Console.exe"),
    incoming_dir=Path(r"D:\incoming"),
    profile_name=None,
    driver="twain",
    device_name="Canon G600 series Network",
    timeout_seconds=120,
)

storage_settings = StorageSettings(
    archive_root=Path(r"D:\archive_test"),
)


def print_checks(title, checks):
    print()
    print(title)
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.message}")
        if check.details:
            print(f"       {check.details}")


print_checks("SCANNER", check_scanner_environment(scanner_settings))
print_checks("STORAGE", check_storage_environment(storage_settings))
