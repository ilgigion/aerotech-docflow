import logging

from app.scanner import ScannerError, ScannerSettings, scan_document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

settings = ScannerSettings(
    incoming_dir=r"D:\PROG_PROJECTS\aerotech-docflow\data\incoming",

    # Впиши точное имя профиля NAPS2, который работает в приложении.
    profile_name="Canon G600 series Network",

    timeout_seconds=120,
)

try:
    pdf_path = scan_document(
        task_id="TEST_001",
        settings=settings,
    )

    print()
    print("OK")
    print(f"PDF создан: {pdf_path}")

except ScannerError as exc:
    print()
    print("ОШИБКА СКАНИРОВАНИЯ")
    print(exc.to_operator_text())

    print()
    print("Техническая информация:")
    print(exc.to_log_dict())
