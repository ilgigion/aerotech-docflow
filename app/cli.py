from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from app.configuration import (
    ConfigurationFileError,
    apply_configuration,
    default_config_path,
    effective_environment_snapshot,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _print_json(data: Any, *, ascii_only: bool = False) -> None:
    print(json.dumps(data, ensure_ascii=ascii_only, indent=2, default=_json_default))


def _prompt(label: str, default: str | None = None, *, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("Значение обязательно.")


def _prompt_yes_no(label: str, *, default: bool) -> bool:
    marker = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{marker}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "д", "да"}:
            return True
        if value in {"n", "no", "н", "нет"}:
            return False
        print("Введите yes или no.")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_string_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _write_configuration_atomic(path: Path, content: str, *, overwrite: bool) -> None:
    path = path.resolve(strict=False)
    if path.exists() and not overwrite:
        raise ConfigurationFileError(
            f"Configuration already exists: {path}. Use --force to replace it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def configure_command(args: argparse.Namespace) -> None:
    output = Path(args.output or args.config or default_config_path()).resolve(strict=False)
    print("Aerotech Docflow: мастер конфигурации")
    print(f"Файл: {output}")
    print("Мастер не создаёт и не изменяет корень архива.")

    production = _prompt_yes_no("Production-режим", default=True)
    environment = "production" if production else "development"
    version = _prompt("Версия сборки", "1.0.0" if production else "dev")
    program_data = Path(os.getenv("PROGRAMDATA", "").strip() or Path.home()) / "Aerotech Docflow"
    program_files = os.getenv("PROGRAMFILES", "").strip()
    naps2_candidate = (
        Path(program_files) / "NAPS2" / "NAPS2.Console.exe"
        if program_files
        else None
    )
    naps2_default = str(naps2_candidate) if naps2_candidate and naps2_candidate.is_file() else None
    naps2 = Path(
        _prompt("NAPS2.Console.exe", naps2_default)
    ).resolve(strict=False)
    if not naps2.is_file():
        raise ConfigurationFileError(f"NAPS2 executable not found: {naps2}")
    profile = _prompt("Имя профиля NAPS2 (пусто = direct mode)", "", required=False)

    incoming = Path(
        _prompt("Временный incoming-каталог", str(program_data / "incoming"))
    ).resolve(strict=False)
    archive = Path(_prompt("Корень архива (должен уже существовать)")).resolve(strict=False)
    if not archive.is_dir():
        raise ConfigurationFileError(f"Archive root must already exist: {archive}")
    archive_id = _prompt("Уникальный archive_id", f"aerotech-archive-{uuid4().hex[:12]}")
    allowed_types = [
        value.strip()
        for value in _prompt("Типы документов через запятую").split(",")
        if value.strip()
    ]
    min_year = int(_prompt("Минимальный год документа", "2020"))
    max_year = int(_prompt("Максимальный год документа", "2030"))

    log_dir = Path(_prompt("Каталог логов", str(program_data / "logs"))).resolve(strict=False)
    idempotency_dir = Path(
        _prompt("Каталог idempotency", str(program_data / "data" / "idempotency"))
    ).resolve(strict=False)

    if _prompt_yes_no("Создать incoming/log/idempotency каталоги", default=True):
        for directory in (incoming, log_dir, idempotency_dir):
            directory.mkdir(parents=True, exist_ok=True)

    direct_values = {
        "driver": "escl",
        "device_name": "",
        "source": "duplex",
        "dpi": 300,
        "page_size": "a4",
        "bit_depth": "gray",
    }
    if not profile:
        direct_values = {
            "driver": _prompt("Драйвер", "escl"),
            "device_name": _prompt("Имя устройства"),
            "source": _prompt("Источник", "duplex"),
            "dpi": int(_prompt("DPI", "300")),
            "page_size": _prompt("Размер страницы", "a4"),
            "bit_depth": _prompt("Цвет", "gray"),
        }

    content = f'''[application]
environment = {_toml_string(environment)}
version = {_toml_string(version)}
host = "127.0.0.1"
port = 8000

[scanner]
naps2_executable = {_toml_string(str(naps2))}
profile = {_toml_string(profile)}
output_encoding = "cp866"
incoming_dir = {_toml_string(str(incoming))}
timeout_seconds = 180
timeout_kill_grace_seconds = 10
verify_process_exit_seconds = 5
quarantine_failed_outputs = true
failed_scan_dir_name = "_failed_runtime"
min_pdf_size_bytes = 100
min_pdf_pages = 1
stable_checks = 2
stable_interval_seconds = 0.5

[scanner.direct]
driver = {_toml_string(str(direct_values['driver']))}
device_name = {_toml_string(str(direct_values['device_name']))}
source = {_toml_string(str(direct_values['source']))}
dpi = {int(direct_values['dpi'])}
page_size = {_toml_string(str(direct_values['page_size']))}
bit_depth = {_toml_string(str(direct_values['bit_depth']))}

[archive]
root = {_toml_string(str(archive))}
confirmation = {_toml_string(str(archive))}
archive_id = {_toml_string(archive_id)}
allowed_doc_types = {_toml_string_list(allowed_types)}
min_document_year = {min_year}
max_document_year = {max_year}

[storage]
copy_buffer_size = 1048576
keep_temp_on_error = false
reservation_stale_seconds = 1800

[locking]
stale_seconds = 1800
wait_timeout_seconds = 0.0
retry_interval_seconds = 0.5
allow_stale_takeover = true

[logging]
enabled = true
level = "INFO"
directory = {_toml_string(str(log_dir))}
max_bytes = 52428800
backup_count = 5
retention_months = 12

[idempotency]
enabled = true
directory = {_toml_string(str(idempotency_dir))}
stale_seconds = 1800

[cleanup]
quarantine_dir_name = "_failed"
managed_prefix = "PF_"
managed_suffix = ".pdf"
min_age_seconds = 86400
skip_if_lock_exists = true
stable_checks = 2
stable_interval_seconds = 0.2
'''
    _write_configuration_atomic(output, content, overwrite=args.force)
    print(f"Конфигурация сохранена: {output}")
    print(f"Проверьте marker архива: {archive / '.aerotech-docflow-archive.json'}")
    print(f"Следующий шаг: aerotech-docflow.exe --config \"{output}\" preflight")


def show_config_command(args: argparse.Namespace) -> None:
    result = apply_configuration(args.config)
    _print_json(
        {
            "config_path": str(result.path) if result.path else None,
            "config_loaded": result.loaded,
            "overridden_by_environment": list(result.overridden_by_environment),
            "effective_environment": effective_environment_snapshot(),
        },
        ascii_only=args.ascii,
    )


def preflight_command(args: argparse.Namespace) -> None:
    apply_configuration(args.config)
    from app.preflight import build_preflight_report

    _print_json(build_preflight_report())


def diagnose_command(args: argparse.Namespace) -> None:
    applied = apply_configuration(args.config)
    from app.production_config import load_runtime_safety_config
    from app.scanner_recovery import diagnose_scanner_state

    config = load_runtime_safety_config()
    try:
        stale = int(os.environ["SCANNER_LOCK_STALE_SECONDS"])
    except KeyError as exc:
        raise ConfigurationFileError(
            "locking.stale_seconds is required for diagnostics"
        ) from exc
    report = diagnose_scanner_state(
        incoming_dir=config.incoming_dir,
        archive_root=config.archive_root,
        lock_stale_after_seconds=stale,
    )
    data = asdict(report)
    data["config_path"] = str(applied.path) if applied.path else None
    data["config_loaded"] = applied.loaded
    data["has_risk_markers"] = report.has_risk_markers
    _print_json(data)


def run_command(args: argparse.Namespace) -> None:
    apply_configuration(args.config)
    from app.run_local_api import main as run_api

    run_api(configuration_already_applied=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docflow", description="Aerotech Docflow service CLI")
    parser.add_argument(
        "--config",
        help="TOML configuration path; defaults to DOCFLOW_CONFIG_FILE or ProgramData",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure", help="Interactive machine configuration wizard")
    configure.add_argument("--output", help="Destination config.toml path")
    configure.add_argument("--force", action="store_true", help="Replace an existing configuration")
    configure.set_defaults(handler=configure_command)

    show = subparsers.add_parser("show-config", help="Show effective configuration and overrides")
    show.add_argument(
        "--ascii",
        action="store_true",
        help="Escape Unicode for code-page-safe machine parsing",
    )
    show.set_defaults(handler=show_config_command)

    preflight = subparsers.add_parser("preflight", help="Validate production configuration without scanning")
    preflight.set_defaults(handler=preflight_command)

    diagnose = subparsers.add_parser("diagnose", help="Read-only scanner/archive runtime diagnostics")
    diagnose.set_defaults(handler=diagnose_command)

    run = subparsers.add_parser("run", help="Run the localhost API")
    run.set_defaults(handler=run_command)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (ConfigurationFileError, ValueError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
