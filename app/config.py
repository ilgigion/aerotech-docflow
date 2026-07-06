"""Конфигурация приложения."""

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Настройки backend-сервиса."""

    scan_inbox: Path
    scan_timeout_seconds: float
    scan_poll_interval_seconds: float
    scan_stable_checks: int


settings = Settings(
    scan_inbox=Path(
        os.getenv(
            "SCAN_INBOX",
            str(PROJECT_ROOT / "data" / "incoming"),
        )
    ),
    scan_timeout_seconds=float(
        os.getenv("SCAN_TIMEOUT_SECONDS", "120")
    ),
    scan_poll_interval_seconds=float(
        os.getenv("SCAN_POLL_INTERVAL_SECONDS", "1")
    ),
    scan_stable_checks=int(
        os.getenv("SCAN_STABLE_CHECKS", "3")
    ),
)