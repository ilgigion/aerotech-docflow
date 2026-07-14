from pathlib import Path
import logging

from app.locks import ScannerLockBusyError, ScannerLockSettings, read_lock_info, scanner_lock


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


lock_path = Path(r"D:\incoming\.scanner_test.lock")
lock_path.parent.mkdir(parents=True, exist_ok=True)
lock_path.unlink(missing_ok=True)

settings = ScannerLockSettings(
    stale_after_seconds=30 * 60,
    wait_timeout_seconds=0,
    retry_interval_seconds=0.5,
    allow_stale_takeover=True,
)


print()
print("TEST 1: lock должен создаться")

with scanner_lock(
    lock_path=lock_path,
    operation_id="LOCK_TEST_001",
    task_id="TEST_LOCK",
    settings=settings,
):
    print("OK: lock создан")
    print(read_lock_info(lock_path))

    print()
    print("TEST 2: второй lock должен получить ошибку scanner_locked")

    try:
        with scanner_lock(
            lock_path=lock_path,
            operation_id="LOCK_TEST_002",
            task_id="TEST_LOCK_2",
            settings=settings,
        ):
            print("ОШИБКА: второй lock не должен был захватиться")

    except ScannerLockBusyError as exc:
        print("OK: второй запуск заблокирован")
        print(exc.to_operator_text())
        print(exc.to_log_dict())


print()
print("TEST 3: после выхода lock должен удалиться")

if lock_path.exists():
    print("ОШИБКА: lock остался")
    print(read_lock_info(lock_path))
else:
    print("OK: lock удалён")
