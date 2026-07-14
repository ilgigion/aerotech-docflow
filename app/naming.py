from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import re


logger = logging.getLogger(__name__)

MAX_DOC_TYPE_LENGTH = 30
MAX_DOCUMENT_NUMBER_LENGTH = 80
MAX_FILENAME_LENGTH = 180

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class NamingError(ValueError):
    """
    Базовая ошибка формирования имени файла.

    operator_message — короткое сообщение для оператора.
    technical_message — подробности для логов.
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


class InvalidFileNameError(NamingError):
    pass


@dataclass(frozen=True)
class DocumentNamingData:
    """
    Данные, из которых собирается имя документа.

    Пример:
        doc_type="УПД"
        document_datetime=datetime(2026, 7, 10, 10, 10, 25)
        document_number="2455B"

    Результат:
        УПД_260710_101025_2455B.pdf
    """

    doc_type: str
    document_datetime: datetime
    document_number: str


@dataclass(frozen=True)
class NormalizationResult:
    """
    Результат нормализации части имени.

    changed=True означает, что входное значение было очищено:
    например, убраны запрещённые символы или пробелы.
    """

    original: str
    normalized: str
    changed: bool


def parse_document_datetime(value: datetime | str) -> datetime:
    """
    Приводит входную дату/время к datetime.

    Финальное имя всегда содержит секунды.
    Если входная строка без секунд, секунды будут равны 00.
    """

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise InvalidDocumentDateTimeError(
            code="invalid_document_datetime_type",
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
            continue

    raise InvalidDocumentDateTimeError(
        code="unsupported_document_datetime_format",
        operator_message="Дата документа указана в неподдерживаемом формате.",
        technical_message=(
            f"Unsupported datetime format: {value!r}. "
            "Supported examples: 2026-07-10 10:10:25, 10.07.2026 10:10:25"
        ),
    )


def _normalize_filename_part_with_result(value: str, field_name: str) -> NormalizationResult:
    """
    Чистит часть имени файла и возвращает информацию о том, изменилось ли значение.

    Что делаем:
    - убираем пробелы по краям;
    - заменяем пробелы внутри на _;
    - убираем символы, запрещённые в Windows-файлах;
    - убираем управляющие символы;
    - схлопываем повторяющиеся _;
    - не ломаем кириллицу.
    """

    if value is None:
        original = ""
    else:
        original = str(value)

    result = original.strip()

    # Запрещённые символы Windows: < > : " / \ | ? *
    result = re.sub(r'[<>:"/\\|?*]+', "_", result)

    # Управляющие символы тоже нельзя использовать в имени файла.
    result = re.sub(r"[\x00-\x1f]+", "_", result)

    # Любые пробелы заменяем на подчёркивание.
    result = re.sub(r"\s+", "_", result)

    # Несколько подчёркиваний подряд превращаем в одно.
    result = re.sub(r"_+", "_", result)

    # Windows плохо относится к именам, заканчивающимся точкой или пробелом.
    result = result.strip("_.")

    # Защита от зарезервированных имён Windows.
    if result.upper() in WINDOWS_RESERVED_NAMES:
        result = f"{result}_"

    changed = result != original

    if changed:
        logger.info(
            "Normalized filename part: field=%s original=%r normalized=%r",
            field_name,
            original,
            result,
        )

    return NormalizationResult(
        original=original,
        normalized=result,
        changed=changed,
    )


def normalize_filename_part(value: str, field_name: str) -> str:
    return _normalize_filename_part_with_result(value, field_name).normalized


def normalize_doc_type(doc_type: str) -> str:
    result = normalize_filename_part(doc_type, "doc_type").upper()

    if not result:
        raise InvalidDocTypeError(
            code="empty_doc_type",
            operator_message="Не указан тип документа.",
            technical_message=f"doc_type={doc_type!r}",
        )

    if len(result) > MAX_DOC_TYPE_LENGTH:
        raise InvalidDocTypeError(
            code="doc_type_too_long",
            operator_message="Тип документа слишком длинный.",
            technical_message=(
                f"doc_type length={len(result)}, max={MAX_DOC_TYPE_LENGTH}, value={result!r}"
            ),
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

    if len(result) > MAX_DOCUMENT_NUMBER_LENGTH:
        raise InvalidDocumentNumberError(
            code="document_number_too_long",
            operator_message="Номер документа слишком длинный.",
            technical_message=(
                f"document_number length={len(result)}, "
                f"max={MAX_DOCUMENT_NUMBER_LENGTH}, value={result!r}"
            ),
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

    Пример:
        УПД_260710_101025_2455B.pdf
    """

    normalized_doc_type = normalize_doc_type(doc_type)
    normalized_document_number = normalize_document_number(document_number)
    parsed_datetime = parse_document_datetime(document_datetime)

    date_part = parsed_datetime.strftime("%y%m%d")
    time_part = parsed_datetime.strftime("%H%M%S")

    file_name = f"{normalized_doc_type}_{date_part}_{time_part}_{normalized_document_number}.pdf"

    if len(file_name) > MAX_FILENAME_LENGTH:
        raise InvalidFileNameError(
            code="filename_too_long",
            operator_message="Итоговое имя файла слишком длинное.",
            technical_message=(
                f"filename length={len(file_name)}, max={MAX_FILENAME_LENGTH}, value={file_name!r}"
            ),
        )

    return file_name


def build_document_naming_data(
    doc_type: str,
    document_datetime: datetime | str,
    document_number: str,
) -> DocumentNamingData:
    return DocumentNamingData(
        doc_type=normalize_doc_type(doc_type),
        document_datetime=parse_document_datetime(document_datetime),
        document_number=normalize_document_number(document_number),
    )
