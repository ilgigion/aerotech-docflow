from datetime import datetime

from app.naming import build_document_filename, normalize_doc_type, normalize_document_number

assert build_document_filename("упд", datetime(2026, 7, 10, 10, 10, 25), "2455B") == "УПД_260710_101025_2455B.pdf"
assert normalize_doc_type(" нкл ") == "НКЛ"
assert normalize_document_number(" 001 / A ") == "001_A"

print("OK: naming")
