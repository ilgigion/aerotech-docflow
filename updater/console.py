from __future__ import annotations

import ctypes
import os
import sys

from updater.errors import UpdaterError


def prepare_console() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("Aerotech Docflow Updater")
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def ok(message: str) -> None:
    print(f"[OK] {message}")


def step(number: int, total: int, message: str) -> None:
    print(f"[{number}/{total}] {message}")


def detail(message: str) -> None:
    print(f"      {message}")


def activity(message: str) -> None:
    print(f"[...] {message}")


def wait_for_key(
    message: str = "Нажмите любую клавишу для выхода.",
    *,
    require_interactive: bool = False,
) -> None:
    print()
    print(message)
    if not sys.stdin.isatty():
        if require_interactive:
            raise UpdaterError(
                "INTERACTIVE_CONSOLE_REQUIRED",
                "Для начала обновления требуется видимое интерактивное консольное окно.",
            )
        return
    if os.name == "nt":
        import msvcrt

        msvcrt.getwch()
    else:
        input()
