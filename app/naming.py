from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


class NamingError(ValueError):
    """
    Базовая ошибка формирования имени файла.
    """

    def __init__(
        self,
        code: str,
        operator_message: str,
        technical_message: str = "",
    ):
        super().__init__(operator_message)

        self.code = code
        self.operator_message = operator_message
        self.technical_message = technical_message

    def to_operator_text(self) -> str:
        return self.operator_message

    def to_log_dict(self) -> dict:
        return {
            "code": self.code,
            "operator_message": self.operator_message,
            "technical_message": self.technical_message,
        }


class InvalidDocTypeError(NamingError):
    pass


class InvalidDocumentNumberError(NamingError):
    pass


class InvalidDocumentDateTimeError(NamingError):
    pass


@dataclass(frozen=True)
class DocumentNamingData:
    """
    Данные, из которых собирается имя документа.

    Пример:
        doc_type="УПД"
        document_datetime=datetime(2026, 7, 10, 10, 10)
        document_number="2455B"

    Результат:
        УПД_260710_1010_2455B.pdf
    """

    doc_type: str
    document_datetime: datetime
    document_number: str


def parse_document_datetime(value: datetime | str) -> datetime:
    """
    Приводим дату/время к datetime.

    Поддерживаем несколько удобных форматов, чтобы потом было проще
    принимать данные из Planfix или тестов.
    """

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise InvalidDocumentDateTimeError(
            code="invalid_document_datetime",
            operator_message="Некорректная дата документа.",
            technical_message=f"Expected datetime or str, got {type(value).__name__}",
        )

    raw_value = value.strip()

    if not raw_value:
        raise InvalidDocumentDateTimeError(
            code="empty_document_datetime",
            operator_message="Не указана дата документа.",
            technical_message="document_datetime is empty",
        )

    supported_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%y%m%d_%H%M%S",
        "%y%m%d_%H%M",
    ]

    for date_format in supported_formats:
        try:
            return datetime.strptime(raw_value, date_format)
        except ValueError:
            pass

    raise InvalidDocumentDateTimeError(
        code="unsupported_document_datetime_format",
        operator_message="Дата документа указана в неподдерживаемом формате.",
        technical_message=f"Unsupported datetime format: {value!r}",
    )


def normalize_filename_part(value: str, field_name: str) -> str:
    """
    Чистим часть имени файла.

    Что делаем:
    - убираем пробелы по краям;
    - заменяем пробелы внутри на _;
    - убираем символы, запрещённые в Windows-файлах;
    - схлопываем повторяющиеся _;
    - не ломаем кириллицу.
    """

    if value is None:
        return ""

    result = str(value).strip()

    # Запрещённые символы Windows:
    # < > : " / \ | ? *
    result = re.sub(r'[<>:"/\\|?*]+', "_", result)

    # Управляющие символы тоже нельзя использовать в имени файла.
    result = re.sub(r"[\x00-\x1f]+", "_", result)

    # Любые пробелы заменяем на подчёркивание.
    result = re.sub(r"\s+", "_", result)

    # Несколько подчёркиваний подряд превращаем в одно.
    result = re.sub(r"_+", "_", result)

    result = result.strip("_.")

    return result


def normalize_doc_type(doc_type: str) -> str:
    result = normalize_filename_part(doc_type, "doc_type").upper()

    if not result:
        raise InvalidDocTypeError(
            code="empty_doc_type",
            operator_message="Не указан тип документа.",
            technical_message=f"doc_type={doc_type!r}",
        )

    return result


def normalize_document_number(document_number: str) -> str:
    result = normalize_filename_part(document_number, "document_number")

    if not result:
        raise InvalidDocumentNumberError(
            code="empty_document_number",
            operator_message="Не указан номер документа.",
            technical_message=f"document_number={document_number!r}",
        )

    return result


def build_document_filename(
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
) -> str:
    """
    Формирует имя документа.

    Финальный шаблон:
        ТИП_ГГММДД_ЧЧММСС_НОМЕР.pdf

    Где:
        ТИП       — входной тип документа
        ГГММДД    — дата из входного document_datetime
        ЧЧММСС    — время из входного document_datetime
        НОМЕР     — входной номер документа

    Пример:
        УПД_260710_101025_2455B.pdf
    """

    normalized_doc_type = normalize_doc_type(doc_type)
    normalized_document_number = normalize_document_number(document_number)
    parsed_datetime = parse_document_datetime(document_datetime)

    date_part = parsed_datetime.strftime("%y%m%d")
    time_part = parsed_datetime.strftime("%H%M%S")

    return f"{normalized_doc_type}_{date_part}_{time_part}_{normalized_document_number}.pdf"


def build_document_naming_data(
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
) -> DocumentNamingData:
    """
    Дополнительная функция, если дальше захочется передавать
    не отдельные параметры, а один объект.
    """

    return DocumentNamingData(
        doc_type=normalize_doc_type(doc_type),
        document_datetime=parse_document_datetime(document_datetime),
        document_number=normalize_document_number(document_number),
    )