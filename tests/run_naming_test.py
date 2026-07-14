from datetime import datetime

from app.naming import NamingError, build_document_filename


cases = [
    {
        "doc_type": "УПД",
        "document_datetime": datetime(2026, 7, 10, 10, 10, 25),
        "document_number": "2455B",
    },
    {
        "doc_type": " упд ",
        "document_datetime": "2026-07-10 10:10:25",
        "document_number": " 2455B ",
    },
    {
        "doc_type": "УПД/ТОРГ",
        "document_datetime": "10.07.2026 10:10:25",
        "document_number": "2455/B ? test",
    },
]


try:
    for case in cases:
        print(build_document_filename(**case))

except NamingError as exc:
    print()
    print("ОШИБКА ФОРМИРОВАНИЯ ИМЕНИ")
    print(exc.to_operator_text())
    print(exc.to_log_dict())
