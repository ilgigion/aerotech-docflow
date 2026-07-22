from __future__ import annotations

import os
from pathlib import Path
import tempfile
import json
import argparse
import builtins
from contextlib import redirect_stdout
import io

from app.configuration import (
    ConfigurationFileError,
    apply_configuration,
    load_config_environment,
)


def _toml_string_for_test(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


with tempfile.TemporaryDirectory() as temp_value:
    root = Path(temp_value)
    config_path = root / "config.toml"
    config_path.write_text(
        r'''[application]
environment = "production"
version = "1.2.3"
host = "127.0.0.1"
port = 8123

[scanner]
naps2_executable = "C:\\Program Files\\NAPS2\\NAPS2.Console.exe"
profile = "TEST PROFILE"
incoming_dir = "D:\\incoming"
quarantine_failed_outputs = true

[scanner.direct]
driver = "escl"
device_name = "TEST DEVICE"
dpi = 300

[archive]
root = "D:\\archive"
allowed_doc_types = ["НКЛ", "УПД"]

[logging]
enabled = true

[idempotency]
enabled = false
''',
        encoding="utf-8",
    )

    values = load_config_environment(config_path)
    assert values["DOCFLOW_ENV"] == "production"
    assert values["DOCFLOW_PORT"] == "8123"
    assert values["SCANNER_QUARANTINE_FAILED_OUTPUTS"] == "1"
    assert values["DOCFLOW_ALLOWED_DOC_TYPES"] == "НКЛ,УПД"
    assert values["DOCFLOW_IDEMPOTENCY_ENABLED"] == "0"

    isolated_environment = {"ARCHIVE_ROOT": r"E:\explicit-archive"}
    applied = apply_configuration(config_path, environ=isolated_environment)
    assert applied.loaded
    assert applied.path == config_path.resolve()
    assert isolated_environment["ARCHIVE_ROOT"] == r"E:\explicit-archive"
    assert isolated_environment["DOCFLOW_ENV"] == "production"
    assert "ARCHIVE_ROOT" in applied.overridden_by_environment
    assert "DOCFLOW_ENV" in applied.applied_environment

    unknown_path = root / "unknown.toml"
    unknown_path.write_text("[archive]\nroot = 'D:/archive'\nunsafe = true\n", encoding="utf-8")
    try:
        load_config_environment(unknown_path)
    except ConfigurationFileError as exc:
        assert "archive.unsafe" in str(exc)
    else:
        raise AssertionError("unknown configuration key was accepted")

    invalid_list = root / "invalid-list.toml"
    invalid_list.write_text(
        "[archive]\nallowed_doc_types = ['GOOD', 'BAD,VALUE']\n",
        encoding="utf-8",
    )
    try:
        load_config_environment(invalid_list)
    except ConfigurationFileError as exc:
        assert "commas" in str(exc)
    else:
        raise AssertionError("ambiguous comma-separated value was accepted")

    try:
        apply_configuration(root / "missing.toml", environ={})
    except ConfigurationFileError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("explicit missing configuration was silently ignored")

    archive = root / "archive"
    incoming = root / "incoming"
    logs = root / "logs"
    records = root / "idempotency"
    naps2 = root / "NAPS2.Console.exe"
    for directory in (archive, incoming, logs, records):
        directory.mkdir()
    naps2.write_bytes(b"unit executable placeholder")
    (archive / ".aerotech-docflow-archive.json").write_text(
        '{"marker":"aerotech-docflow-archive-v1","archive_id":"unit-config-archive"}',
        encoding="utf-8",
    )
    production_path = root / "production.toml"
    production_path.write_text(
        f'''[application]
environment = "production"
version = "1.0.0-unit"
host = "127.0.0.1"
port = 8000
[scanner]
naps2_executable = {_toml_string_for_test(str(naps2))}
profile = "TEST PROFILE"
output_encoding = "utf-8"
incoming_dir = {_toml_string_for_test(str(incoming))}
timeout_seconds = 180
timeout_kill_grace_seconds = 10
verify_process_exit_seconds = 5
quarantine_failed_outputs = true
failed_scan_dir_name = "_failed_runtime"
min_pdf_size_bytes = 100
min_pdf_pages = 1
stable_checks = 2
stable_interval_seconds = 0.5
[archive]
root = {_toml_string_for_test(str(archive))}
confirmation = {_toml_string_for_test(str(archive.resolve()))}
archive_id = "unit-config-archive"
allowed_doc_types = ["НКЛ"]
min_document_year = 2020
max_document_year = 2030
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
directory = {_toml_string_for_test(str(logs))}
max_bytes = 1000000
backup_count = 2
retention_months = 3
[idempotency]
enabled = true
directory = {_toml_string_for_test(str(records))}
stale_seconds = 1800
[cleanup]
quarantine_dir_name = "_failed"
managed_prefix = "PF_"
managed_suffix = ".pdf"
min_age_seconds = 86400
skip_if_lock_exists = true
stable_checks = 2
stable_interval_seconds = 0.2
''',
        encoding="utf-8",
    )
    original_environment = os.environ.copy()
    try:
        os.environ.clear()
        apply_configuration(production_path)
        from app.production_config import validate_runtime_environment

        validated = validate_runtime_environment()
        assert validated.production
        assert validated.archive_root.resolve() == archive.resolve()
    finally:
        os.environ.clear()
        os.environ.update(original_environment)

    wizard_output = root / "wizard.toml"
    wizard_incoming = root / "wizard-incoming"
    wizard_logs = root / "wizard-logs"
    wizard_records = root / "wizard-idempotency"
    answers = iter(
        [
            "no",
            "",
            str(naps2),
            "TEST PROFILE",
            str(wizard_incoming),
            str(archive),
            "wizard-archive",
            "НКЛ,УПД",
            "2021",
            "2031",
            str(wizard_logs),
            str(wizard_records),
            "yes",
        ]
    )
    original_input = builtins.input
    try:
        builtins.input = lambda prompt="": next(answers)
        from app.cli import configure_command

        configure_command(
            argparse.Namespace(
                output=str(wizard_output),
                config=None,
                force=False,
            )
        )
    finally:
        builtins.input = original_input
    wizard_values = load_config_environment(wizard_output)
    assert wizard_values["DOCFLOW_ENV"] == "development"
    assert wizard_values["DOCFLOW_ARCHIVE_ID"] == "wizard-archive"
    assert wizard_values["DOCFLOW_ALLOWED_DOC_TYPES"] == "НКЛ,УПД"
    assert wizard_values["SCANNER_STABLE_INTERVAL_SECONDS"] == "0.5"
    assert wizard_values["INCOMING_CLEANUP_MIN_AGE_SECONDS"] == "86400"
    assert wizard_values["INCOMING_CLEANUP_STABLE_INTERVAL_SECONDS"] == "0.2"
    assert wizard_values["SCANNER_LOCK_RETRY_INTERVAL_SECONDS"] == "0.5"
    assert wizard_incoming.is_dir()
    assert wizard_logs.is_dir()
    assert wizard_records.is_dir()

    project_root = Path(__file__).resolve().parents[2]
    installer = (project_root / "packaging" / "install_current_machine.ps1").read_text(
        encoding="utf-8"
    )
    cleanup = (project_root / "packaging" / "cleanup_previous_install.ps1").read_text(
        encoding="utf-8"
    )
    updater = (project_root / "packaging" / "update_current_machine.ps1").read_text(
        encoding="utf-8"
    )
    build_script = (project_root / "packaging" / "build_windows.ps1").read_text(
        encoding="utf-8"
    )
    assert '"D:\\Archive"' not in installer
    assert '"D:\\incoming"' not in installer
    assert "aerotech-primary-archive" not in installer
    assert "effective_environment" in installer
    assert "show-config --ascii" in installer
    assert "Remove-Item -LiteralPath $Marker" not in cleanup
    assert "Assert-NoScannerActivity $ScannerLock" in updater
    assert updater.count("Assert-NoScannerActivity $ScannerLock") == 2
    assert "Stop-InstalledApplication $ResolvedInstall" in updater
    assert "Assert-PackageManifest $ResolvedSource" in updater
    assert "Get-FileHash -LiteralPath $ConfigBackup -Algorithm SHA256" in updater
    assert "Move-Item -LiteralPath $ResolvedInstall -Destination $RollbackDir" in updater
    assert "Move-Item -LiteralPath $RollbackDir -Destination $ResolvedInstall" in updater
    assert "--config $ResolvedConfig preflight" in updater
    assert "docflow-service.xml" in updater
    assert "Start-Service" not in updater
    assert "Remove-Item -LiteralPath $ResolvedInstall" not in updater
    assert '"packaging\\update_current_machine.ps1"' in build_script

    from app.cli import _print_json

    ascii_output = io.StringIO()
    with redirect_stdout(ascii_output):
        _print_json({"path": "D:\\Архив\\НКЛ"}, ascii_only=True)
    ascii_payload = ascii_output.getvalue()
    ascii_payload.encode("ascii")
    assert json.loads(ascii_payload)["path"] == "D:\\Архив\\НКЛ"


original_host = os.environ.get("DOCFLOW_HOST")
original_port = os.environ.get("DOCFLOW_PORT")
try:
    from app.production_config import ProductionConfigurationError, validate_runtime_environment

    os.environ["DOCFLOW_HOST"] = "0.0.0.0"
    try:
        validate_runtime_environment()
    except ProductionConfigurationError as exc:
        assert "localhost-only" in str(exc)
    else:
        raise AssertionError("non-local API host was accepted")

    os.environ["DOCFLOW_HOST"] = "127.0.0.1"
    os.environ["DOCFLOW_PORT"] = "70000"
    try:
        validate_runtime_environment()
    except ProductionConfigurationError as exc:
        assert "1..65535" in str(exc)
    else:
        raise AssertionError("out-of-range API port was accepted")
finally:
    if original_host is None:
        os.environ.pop("DOCFLOW_HOST", None)
    else:
        os.environ["DOCFLOW_HOST"] = original_host
    if original_port is None:
        os.environ.pop("DOCFLOW_PORT", None)
    else:
        os.environ["DOCFLOW_PORT"] = original_port


print("OK")
