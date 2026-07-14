from datetime import datetime

from app.naming import NamingError, build_document_filename


def test_success_from_datetime():
    filename = build_document_filename(
        doc_type="УПД",
        document_datetime=datetime(2026, 7, 10, 10, 10, 25),
        document_number="2455B",
    )

    print(filename)


def test_success_from_string():
    filename = build_document_filename(
        doc_type=" упд ",
        document_datetime="2026-07-10 10:10:25",
        document_number=" 2455B ",
    )

    print(filename)


try:
    test_success_from_datetime()
    test_success_from_string()

except NamingError as exc:
    print()
    print("ОШИБКА ФОРМИРОВАНИЯ ИМЕНИ")
    print(exc.to_operator_text())

    print()
    print("Техническая информация:")
    print(exc.to_log_dict())