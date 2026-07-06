"""Ожидание PDF-файла, созданного сканером."""

import asyncio
import time
from pathlib import Path


class ScannerTimeoutError(TimeoutError):
    """Сканер не создал PDF за отведённое время."""


FileSignature = tuple[int, int]


def _get_pdf_files(folder: Path) -> dict[Path, FileSignature]:
    """Получить список PDF и их текущие характеристики."""

    files: dict[Path, FileSignature] = {}

    for file_path in folder.iterdir():
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() != ".pdf":
            continue

        try:
            stat = file_path.stat()
        except OSError:
            continue

        files[file_path] = (
            stat.st_size,
            stat.st_mtime_ns,
        )

    return files


def _is_valid_pdf(file_path: Path) -> bool:
    """Проверить, что файл похож на корректный PDF."""

    try:
        if file_path.stat().st_size == 0:
            return False

        with file_path.open("rb") as pdf_file:
            header = pdf_file.read(1024)

        return b"%PDF-" in header

    except (OSError, PermissionError):
        return False


async def wait_for_new_pdf(
    folder: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    stable_checks: int,
) -> Path:
    """
    Дождаться нового PDF в папке.

    Файл считается готовым, когда его размер и время изменения
    не меняются несколько проверок подряд.
    """

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    initial_files = _get_pdf_files(folder)

    stable_states: dict[
        Path,
        tuple[FileSignature, int],
    ] = {}

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        current_files = _get_pdf_files(folder)

        for file_path, signature in current_files.items():
            initial_signature = initial_files.get(file_path)

            # Старые неизменённые файлы нас не интересуют.
            if initial_signature == signature:
                continue

            previous_state = stable_states.get(file_path)

            if previous_state is None:
                stable_states[file_path] = (
                    signature,
                    1,
                )
                continue

            previous_signature, checks_count = previous_state

            if previous_signature == signature:
                checks_count += 1
            else:
                checks_count = 1

            stable_states[file_path] = (
                signature,
                checks_count,
            )

            if (
                checks_count >= stable_checks
                and _is_valid_pdf(file_path)
            ):
                return file_path.resolve()

        await asyncio.sleep(poll_interval_seconds)

    raise ScannerTimeoutError(
        "PDF не появился в папке сканера "
        f"за {timeout_seconds} секунд: {folder}"
    )