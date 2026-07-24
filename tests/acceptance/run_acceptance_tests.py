from __future__ import annotations

import argparse
from datetime import datetime
import errno
import hashlib
import json
import logging
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

import httpx
from pypdf import PdfWriter

import app.storage as storage_module
from app.configuration import load_config_environment
from app.storage import StorageError, StorageSettings, store_document


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "acceptance_runs"
RUN_MARKER = "aerotech-docflow-acceptance-v1"
logger = logging.getLogger("acceptance")


SCENARIOS: dict[int, dict[str, Any]] = {
    1: {
        "name": "Обычный успешный скан",
        "expectation": "Один валидный PDF в ГОД\\ТИП, корректный ответ и отсутствие изменений чужих файлов.",
        "manual_required": True,
        "automatic": "Naming, storage и API проверены unit-тестами; требуется физический скан.",
    },
    2: {
        "name": "Пустой автоподатчик",
        "expectation": "Нет успеха и архивного PDF; оператор получает понятную ошибку.",
        "manual_required": True,
        "automatic": "Fail-closed проверка PDF автоматизирована; пустой ADF проверяется физически.",
    },
    3: {
        "name": "Замятие или принудительная остановка",
        "expectation": "Частичный PDF не принят, задача не завершена, следующий запуск возможен.",
        "manual_required": True,
        "automatic": "Обработка повреждённого PDF и остановки процесса покрыта unit-тестами.",
    },
    4: {
        "name": "Повтор одного запроса",
        "expectation": "Повтор возвращает существующий результат без второго физического скана.",
        "manual_required": True,
        "automatic": "Решение return_existing проверено unit-тестом идемпотентности.",
    },
    5: {
        "name": "Два одновременных запроса",
        "expectation": "Нет параллельного запуска сканера; второй запрос получает контролируемый результат.",
        "manual_required": True,
        "automatic": "Базовые свойства lock проверены; требуется реальная конкурентная проверка API.",
    },
    6: {
        "name": "Падение после блокировки",
        "expectation": "Lock восстанавливается по правилам и чужой активный lock не удаляется.",
        "manual_required": True,
        "automatic": "Сохранение lock при неостановленном процессе покрыто unit-тестом.",
    },
    7: {
        "name": "Совпадение итогового имени",
        "expectation": "Существующий PDF неизменен, новый файл получает безопасный суффикс.",
        "manual_required": False,
        "automatic": "Выполняется отдельная файловая проверка на тестовом архиве.",
    },
    8: {
        "name": "Недоступный архив",
        "expectation": "Исходный PDF сохранён, успех не возвращён, архив не изменён.",
        "manual_required": False,
        "automatic": "Недоступный корень архива воспроизводится отдельной файловой проверкой.",
    },
    9: {
        "name": "Недостаточно места",
        "expectation": "Нет финального/частичного файла, исходник не удалён, возвращена ошибка.",
        "manual_required": False,
        "automatic": "ENOSPC искусственно внедряется в операцию копирования.",
    },
    10: {
        "name": "Перезапуск сервера или процесса",
        "expectation": "После остановки на трёх стадиях нет повреждённого архива и работа продолжается.",
        "manual_required": True,
        "automatic": "Recovery-примитивы проверены unit-тестами; три kill-point требуют ручного прогона.",
    },
    11: {
        "name": "Защита существующего архива",
        "expectation": "Контрольные суммы всех защищённых файлов до и после совпадают.",
        "manual_required": False,
        "automatic": "Runner создаёт защищённые PDF и сверяет SHA-256.",
    },
    12: {
        "name": "Серия из 20–30 документов",
        "expectation": "Нет пропусков, дублей и lock; все операции связаны с файлами через логи.",
        "manual_required": True,
        "automatic": "Требуется физическая серия документов.",
    },
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return result


def write_checksum_file(path: Path, snapshot: list[dict[str, Any]]) -> None:
    lines = [f"{item['sha256']}  {item['path']}" for item in snapshot]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def git_output(*args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def create_valid_pdf(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": title})
    with path.open("wb") as stream:
        writer.write(stream)


def run_command(run_dir: Path, name: str, command: list[str], timeout: int = 300) -> dict[str, Any]:
    started_at = datetime.now().astimezone().isoformat()
    logger.info("Running command: %s", subprocess.list2cmdline(command))
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = completed.stdout
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + f"\nTIMEOUT AFTER {timeout} SECONDS\n"
        return_code = -1

    log_path = run_dir / "automated" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"COMMAND: {subprocess.list2cmdline(command)}\n"
        f"STARTED_AT: {started_at}\n"
        f"RETURN_CODE: {return_code}\n\n{output}",
        encoding="utf-8",
    )
    logger.info("Command finished: name=%s return_code=%s log=%s", name, return_code, log_path)
    return {
        "command": subprocess.list2cmdline(command),
        "started_at": started_at,
        "return_code": return_code,
        "log": str(log_path.relative_to(run_dir)),
    }


def run_storage_acceptance_probes(run_dir: Path) -> dict[str, Any]:
    probes_root = run_dir / "automated" / "storage_probes"
    probes_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    # Scenario 7: collision must preserve the old PDF and create a suffixed file.
    root = probes_root / "scenario_07"
    incoming = root / "incoming"
    archive = root / "archive"
    incoming.mkdir(parents=True)
    existing = archive / "2026" / "НКЛ" / "НКЛ_260624_135000_001.pdf"
    create_valid_pdf(existing, "protected collision fixture")
    existing_hash = sha256(existing)
    source = incoming / "source.pdf"
    create_valid_pdf(source, "new scan")
    result = store_document(
        source,
        "НКЛ",
        datetime(2026, 6, 24, 13, 50, 0),
        "001",
        settings=StorageSettings(archive_root=archive),
        operation_id="ACCEPTANCE_SCENARIO_07",
    )
    scenario_07_ok = (
        existing_hash == sha256(existing)
        and result.file_name == "НКЛ_260624_135000_001_01.pdf"
        and result.file_path.exists()
        and not source.exists()
    )
    results["7"] = {
        "passed": scenario_07_ok,
        "existing_file": str(existing.relative_to(run_dir)),
        "existing_sha256_before": existing_hash,
        "existing_sha256_after": sha256(existing),
        "created_file": str(result.file_path.relative_to(run_dir)),
        "created_sha256": sha256(result.file_path),
    }

    # Scenario 8: invalid archive root must leave the source untouched.
    root = probes_root / "scenario_08"
    incoming = root / "incoming"
    incoming.mkdir(parents=True)
    source = incoming / "source.pdf"
    create_valid_pdf(source, "unavailable archive")
    source_hash = sha256(source)
    bad_archive = root / "archive_as_file"
    bad_archive.write_text("not a directory", encoding="utf-8")
    error_code = None
    try:
        store_document(
            source,
            "НКЛ",
            datetime(2026, 6, 24, 13, 50, 0),
            "002",
            settings=StorageSettings(archive_root=bad_archive),
            operation_id="ACCEPTANCE_SCENARIO_08",
        )
    except StorageError as exc:
        error_code = exc.code
    scenario_08_ok = source.exists() and sha256(source) == source_hash and error_code is not None
    results["8"] = {
        "passed": scenario_08_ok,
        "error_code": error_code,
        "source_preserved": source.exists(),
        "source_sha256_before": source_hash,
        "source_sha256_after": sha256(source) if source.exists() else None,
    }

    # Scenario 9: injected ENOSPC must not publish or delete the source PDF.
    root = probes_root / "scenario_09"
    incoming = root / "incoming"
    archive = root / "archive"
    incoming.mkdir(parents=True)
    source = incoming / "source.pdf"
    create_valid_pdf(source, "disk full")
    source_hash = sha256(source)
    original_copyfileobj = storage_module.shutil.copyfileobj

    def raise_disk_full(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError(errno.ENOSPC, "No space left on device (acceptance injection)")

    storage_module.shutil.copyfileobj = raise_disk_full
    error_code = None
    try:
        try:
            store_document(
                source,
                "НКЛ",
                datetime(2026, 6, 24, 13, 50, 0),
                "003",
                settings=StorageSettings(archive_root=archive),
                operation_id="ACCEPTANCE_SCENARIO_09",
            )
        except StorageError as exc:
            error_code = exc.code
    finally:
        storage_module.shutil.copyfileobj = original_copyfileobj

    final_pdfs = list(archive.rglob("*.pdf")) if archive.exists() else []
    leftovers = (
        list(archive.rglob("*.tmp")) + list(archive.rglob("*.reserve"))
        if archive.exists()
        else []
    )
    scenario_09_ok = (
        error_code == "atomic_temp_copy_error"
        and source.exists()
        and sha256(source) == source_hash
        and not final_pdfs
        and not leftovers
    )
    results["9"] = {
        "passed": scenario_09_ok,
        "injection": "OSError(errno.ENOSPC) from shutil.copyfileobj",
        "error_code": error_code,
        "source_preserved": source.exists(),
        "source_sha256_before": source_hash,
        "source_sha256_after": sha256(source) if source.exists() else None,
        "published_pdfs": [str(path.relative_to(run_dir)) for path in final_pdfs],
        "temporary_leftovers": [str(path.relative_to(run_dir)) for path in leftovers],
    }

    write_json(run_dir / "automated" / "storage_probes.json", results)
    return results


def create_server_script(run_dir: Path, manifest: dict[str, Any]) -> None:
    paths = manifest["test_environment"]
    config_path = manifest["runtime_config"]
    script = f'''$ErrorActionPreference = "Stop"
$env:DOCFLOW_CONFIG_FILE = "{config_path}"
$env:DOCFLOW_ENV = "development"
$env:SCANNER_INCOMING_DIR = "{paths['incoming']}"
$env:ARCHIVE_ROOT = "{paths['archive']}"
$env:DOCFLOW_LOG_DIR = "{paths['server_logs']}"
$env:DOCFLOW_IDEMPOTENCY_DIR = "{paths['idempotency']}"

Write-Host "ACCEPTANCE RUN: {manifest['run_id']}"
Write-Host "TEST ARCHIVE: $env:ARCHIVE_ROOT"
Write-Host "Production archive is not used."
Set-Location "{PROJECT_ROOT}"
& "{sys.executable}" -m app.run_local_api
'''
    (run_dir / "start_test_api.ps1").write_text(script, encoding="utf-8-sig")


def create_scenario12_script(run_dir: Path, health_url: str) -> None:
    script = f'''param(
    [ValidateRange(1, 20)]
    [int]$StartAt = 1,
    [Parameter(Mandatory = $true)]
    [string]$ScannerProfile
)

$ErrorActionPreference = "Stop"
$run = "{run_dir}"
$python = "{sys.executable}"
$scenarioRoot = Join-Path $run "scenario_12\\manual_attempts"
$docType = [string]([char]0x041D) + [string]([char]0x041A) + [string]([char]0x041B)

try {{
    $health = Invoke-RestMethod -Method Get -Uri "{health_url}" -TimeoutSec 5
}} catch {{
    throw "Test API is unavailable. Restart start_test_api.ps1 after disabling VPN. $($_.Exception.Message)"
}}

Write-Host "API is available. The script will run 20 sequential physical scans."
Write-Host "Load only one test document into the feeder at a time."

for ($index = $StartAt; $index -le 20; $index++) {{
    $number = "{{0:D3}}" -f $index
    $taskId = "ACC-012-$number"
    $documentNumber = "012-$number"

    while ($true) {{
        $confirmation = Read-Host "[$index/20] Load document $number. Type SCAN to start, Q to stop"
        if ($confirmation -match '^[Qq]$') {{
            Write-Host "Series stopped by operator before document $number."
            exit 2
        }}
        if ($confirmation -ieq "SCAN") {{ break }}
        Write-Host "No scan started. Enter the exact word SCAN when the document is ready."
    }}

    & $python -m tests.acceptance.run_acceptance_tests request `
        --run $run `
        --scenario 12 `
        --task-id $taskId `
        --doc-type $docType `
        --document-number $documentNumber `
        --scanner-profile $ScannerProfile `
        --confirm-real-scan

    if ($LASTEXITCODE -ne 0) {{
        throw "Request command exited with code $LASTEXITCODE for document $number."
    }}

    $attempt = Get-ChildItem -LiteralPath $scenarioRoot -Directory |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $attempt) {{ throw "Evidence directory was not found for document $number." }}

    $responsePath = Join-Path $attempt.FullName "response.json"
    $response = Get-Content -LiteralPath $responsePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($response.http_status -ne 200 -or $response.json.status -ne "succeeded") {{
        throw "Document $number failed: HTTP=$($response.http_status), status=$($response.json.status). Evidence: $($attempt.FullName)"
    }}
    Write-Host "Document $number accepted: $($response.json.file_name)"
}}

Write-Host "All 20 requests succeeded. Do not start additional scans."
Write-Host "Enable VPN and run check_scenario12 for final verification."
'''
    scenario_dir = run_dir / "scenario_12"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "run_20_documents.ps1").write_text(script, encoding="ascii")


def create_manual_plan(run_dir: Path) -> None:
    lines = [
        "# Ручная часть приёмки",
        "",
        f"Каталог прогона: `{run_dir}`",
        "",
        "1. Остановите любой ранее запущенный API.",
        "2. Запустите `./start_test_api.ps1` из каталога прогона.",
        "3. Для HTTP-запросов используйте команду `request` runner-а: она сохраняет JSON и ответ.",
        "4. После сценария запишите результат командой `record` и приложите скрин/видео при необходимости.",
        "5. Выполните `finalize`; до заполнения всех ручных сценариев вердикт останется `НЕ ДОПУСКАТЬ`.",
        "",
        "Пример запроса:",
        "",
        "```powershell",
        f'python -m tests.acceptance.run_acceptance_tests request --run "{run_dir}" --scenario 1 --task-id "ACC-001" --doc-type "НКЛ" --document-number "001" --scanner-profile "EPSON DS-790WN" --confirm-real-scan',
        "```",
        "",
        "Пример фиксации результата:",
        "",
        "```powershell",
        f'python -m tests.acceptance.run_acceptance_tests record --run "{run_dir}" --scenario 1 --status PASSED --notes "Один лист, файл проверен" --evidence "C:\\path\\to\\screenshot.png"',
        "```",
        "",
        "## Сценарии",
        "",
    ]
    for scenario_id, scenario in SCENARIOS.items():
        if not scenario["manual_required"]:
            continue
        lines.extend(
            [
                f"### {scenario_id}. {scenario['name']}",
                "",
                scenario["expectation"],
                "",
                "Сохраните входной JSON, HTTP-ответ/консольный результат, operation_id, список файлов до/после, SHA-256 и скрин/видео физического действия.",
                "",
            ]
        )
    (run_dir / "MANUAL_TEST_PLAN.md").write_text("\n".join(lines), encoding="utf-8")


def validate_run_dir(value: str | Path) -> tuple[Path, dict[str, Any]]:
    run_dir = Path(value).resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Нет manifest.json в каталоге прогона: {run_dir}")
    manifest = read_json(manifest_path)
    if manifest.get("marker") != RUN_MARKER:
        raise SystemExit(f"Некорректный marker каталога приёмки: {run_dir}")
    return run_dir, manifest


def start_run(runs_root: Path, config_path: Path) -> Path:
    config_path = config_path.expanduser().resolve(strict=True)
    if not config_path.is_file():
        raise SystemExit(f"Configuration file not found: {config_path}")
    config_values = load_config_environment(config_path)
    api_host = config_values.get("DOCFLOW_HOST", "").strip()
    if api_host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Acceptance config must use localhost-only application.host")
    try:
        api_port = int(config_values["DOCFLOW_PORT"])
    except (KeyError, ValueError) as exc:
        raise SystemExit("Acceptance config must define a valid application.port") from exc
    api_base_url = f"http://{api_host}:{api_port}"
    _, commit = git_output("rev-parse", "HEAD")
    short_commit = commit[:8] if commit else "no-git"
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_commit}"
    run_dir = runs_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    configure_logging(run_dir / "acceptance.log")
    runtime_config_path = run_dir / "runtime_config.toml"
    runtime_config_path.write_bytes(config_path.read_bytes())

    _, status = git_output("status", "--porcelain=v1")
    _, branch = git_output("branch", "--show-current")
    _, remote = git_output("config", "--get", "remote.origin.url")
    _, diff = git_output("diff", "--binary", "HEAD")
    (run_dir / "source_diff.patch").write_text(diff + ("\n" if diff else ""), encoding="utf-8")

    environment_root = run_dir / "test_environment"
    incoming = environment_root / "incoming"
    archive = environment_root / "archive"
    server_logs = environment_root / "server_logs"
    idempotency = environment_root / "idempotency"
    for path in (incoming, archive, server_logs, idempotency):
        path.mkdir(parents=True, exist_ok=True)

    create_valid_pdf(archive / "_protected" / "reference_a.pdf", "protected A")
    create_valid_pdf(archive / "_protected" / "nested" / "reference_b.pdf", "protected B")
    protected_before = snapshot_files(archive / "_protected")
    write_json(run_dir / "protected_before.json", protected_before)
    write_checksum_file(run_dir / "protected_before.sha256", protected_before)

    manifest = {
        "marker": RUN_MARKER,
        "run_id": run_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "project_root": str(PROJECT_ROOT),
        "git": {
            "commit": commit,
            "branch": branch,
            "remote": remote,
            "dirty": bool(status),
            "status": status.splitlines() if status else [],
            "diff_file": "source_diff.patch",
        },
        "runtime": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "runtime_config": str(runtime_config_path),
        "api": {
            "health_url": f"{api_base_url}/health",
            "scan_url": f"{api_base_url}/scan",
        },
        "test_environment": {
            "root": str(environment_root),
            "incoming": str(incoming),
            "archive": str(archive),
            "server_logs": str(server_logs),
            "idempotency": str(idempotency),
        },
    }
    write_json(run_dir / "manifest.json", manifest)
    logger.info("Acceptance run created: %s", run_dir)
    logger.info("Git commit=%s dirty=%s", commit, bool(status))
    logger.info("Test archive=%s", archive)

    automated = {
        "compileall": run_command(
            run_dir,
            "compileall",
            [sys.executable, "-m", "compileall", "app", "tests"],
        ),
        "unit_tests": run_command(
            run_dir,
            "unit_tests",
            [sys.executable, "-m", "tests.unit.run_all_unit_tests"],
        ),
    }
    automated["storage_probes"] = run_storage_acceptance_probes(run_dir)
    write_json(run_dir / "automated" / "summary.json", automated)
    create_server_script(run_dir, manifest)
    create_scenario12_script(run_dir, manifest["api"]["health_url"])
    create_manual_plan(run_dir)
    finalize_run(run_dir, manifest, log_already_configured=True)
    return run_dir


def request_scan(args: argparse.Namespace) -> None:
    run_dir, manifest = validate_run_dir(args.run)
    configure_logging(run_dir / "acceptance.log")
    if not args.confirm_real_scan:
        raise SystemExit("Для физического запроса требуется флаг --confirm-real-scan")

    payload = {
        "task_id": args.task_id,
        "doc_type": args.doc_type,
        "document_number": args.document_number,
        "scanner_profile": args.scanner_profile,
        "idempotency_key": args.idempotency_key,
    }
    if payload["idempotency_key"] is None:
        del payload["idempotency_key"]

    attempt_dir = (
        run_dir
        / f"scenario_{args.scenario:02d}"
        / "manual_attempts"
        / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    attempt_dir.mkdir(parents=True, exist_ok=False)
    write_json(attempt_dir / "input.json", payload)
    write_json(attempt_dir / "archive_before.json", snapshot_files(Path(read_json(run_dir / "manifest.json")["test_environment"]["archive"])))
    request_url = args.url or manifest["api"]["scan_url"]
    command_text = f"POST {request_url}\nContent-Type: application/json\n"
    (attempt_dir / "command.txt").write_text(command_text, encoding="utf-8")

    logger.info("Sending manual acceptance request: scenario=%s task_id=%s", args.scenario, args.task_id)
    try:
        response = post_local_scan_request(request_url, payload, args.timeout)
        response_record = {
            "http_status": response.status_code,
            "headers": dict(response.headers),
            "json": None,
            "text": response.text,
        }
        try:
            response_record["json"] = response.json()
        except ValueError:
            pass
    except Exception as exc:
        response_record = {
            "request_error": type(exc).__name__,
            "message": str(exc),
        }
    write_json(attempt_dir / "response.json", response_record)
    manifest = read_json(run_dir / "manifest.json")
    archive_after = snapshot_files(Path(manifest["test_environment"]["archive"]))
    write_json(attempt_dir / "archive_after.json", archive_after)
    write_checksum_file(attempt_dir / "archive_after.sha256", archive_after)
    logger.info("Manual request evidence saved: %s", attempt_dir)
    print(attempt_dir)


def post_local_scan_request(url: str, payload: dict[str, Any], timeout: float) -> httpx.Response:
    """Send localhost acceptance traffic without inheriting VPN proxy settings."""

    with httpx.Client(trust_env=False, timeout=timeout) as client:
        return client.post(url, json=payload)


def record_manual(args: argparse.Namespace) -> None:
    run_dir, manifest = validate_run_dir(args.run)
    configure_logging(run_dir / "acceptance.log")
    scenario_dir = run_dir / f"scenario_{args.scenario:02d}"
    evidence_dir = scenario_dir / "manual_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for raw_path in args.evidence or []:
        source = Path(raw_path).resolve()
        if not source.exists():
            raise SystemExit(f"Доказательство не найдено: {source}")
        destination = evidence_dir / source.name
        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        copied.append(str(destination.relative_to(run_dir)))

    has_attempt = (scenario_dir / "manual_attempts").exists()
    if args.status in {"PASSED", "FAILED"} and not copied and not has_attempt:
        raise SystemExit("Для PASSED/FAILED требуется --evidence или сохранённый request attempt")

    result = {
        "scenario": args.scenario,
        "status": args.status,
        "recorded_at": datetime.now().astimezone().isoformat(),
        "notes": args.notes,
        "evidence": copied,
    }
    write_json(scenario_dir / "manual_result.json", result)
    logger.info("Manual result recorded: scenario=%s status=%s", args.scenario, args.status)
    finalize_run(run_dir, manifest, log_already_configured=True)


def finalize_run(
    run_dir: Path,
    manifest: dict[str, Any] | None = None,
    *,
    log_already_configured: bool = False,
) -> None:
    if manifest is None:
        run_dir, manifest = validate_run_dir(run_dir)
    if not log_already_configured:
        configure_logging(run_dir / "acceptance.log")

    automated = read_json(run_dir / "automated" / "summary.json")
    compile_ok = automated["compileall"]["return_code"] == 0
    units_ok = automated["unit_tests"]["return_code"] == 0
    probes = automated["storage_probes"]

    protected_root = Path(manifest["test_environment"]["archive"]) / "_protected"
    protected_before = read_json(run_dir / "protected_before.json")
    protected_after = snapshot_files(protected_root)
    protected_unchanged = protected_before == protected_after
    write_json(run_dir / "protected_after.json", protected_after)
    write_checksum_file(run_dir / "protected_after.sha256", protected_after)

    rows = []
    all_scenarios_passed = True
    for scenario_id, scenario in SCENARIOS.items():
        scenario_dir = run_dir / f"scenario_{scenario_id:02d}"
        manual_path = scenario_dir / "manual_result.json"
        manual_result = read_json(manual_path) if manual_path.exists() else None

        automatic_passed = compile_ok and units_ok
        evidence = ["automated/compileall.log", "automated/unit_tests.log"]
        if str(scenario_id) in probes:
            automatic_passed = automatic_passed and bool(probes[str(scenario_id)]["passed"])
            evidence.append("automated/storage_probes.json")
        if scenario_id == 11:
            automatic_passed = automatic_passed and protected_unchanged
            evidence.extend(["protected_before.sha256", "protected_after.sha256"])

        if not automatic_passed:
            status = "FAILED"
            actual = "Автоматическая проверка завершилась ошибкой."
        elif scenario["manual_required"]:
            if manual_result is None:
                status = "PENDING_MANUAL"
                actual = scenario["automatic"] + " Ручной результат ещё не зафиксирован."
            else:
                status = manual_result["status"]
                actual = manual_result.get("notes") or "Ручной результат зафиксирован."
                evidence.append(str(manual_path.relative_to(run_dir)))
                evidence.extend(manual_result.get("evidence", []))
                attempts_root = scenario_dir / "manual_attempts"
                if attempts_root.exists():
                    evidence.extend(
                        str(path.relative_to(run_dir))
                        for path in sorted(attempts_root.iterdir())
                        if path.is_dir()
                    )
        else:
            status = "PASSED"
            if scenario_id == 7:
                probe = probes["7"]
                actual = (
                    "Старый PDF сохранил SHA-256; создан файл с суффиксом _01: "
                    f"{probe['created_file']}."
                )
            elif scenario_id == 8:
                probe = probes["8"]
                actual = (
                    f"Получена ошибка {probe['error_code']}; исходный PDF сохранён "
                    "с прежним SHA-256."
                )
            elif scenario_id == 9:
                probe = probes["9"]
                actual = (
                    f"После ENOSPC получена ошибка {probe['error_code']}; исходник сохранён, "
                    "финальных PDF и временных остатков нет."
                )
            elif scenario_id == 11:
                actual = "SHA-256 двух защищённых PDF, включая вложенную папку, до и после совпадают."
            else:
                actual = scenario["automatic"]

        if status != "PASSED":
            all_scenarios_passed = False
        rows.append(
            {
                "id": scenario_id,
                "name": scenario["name"],
                "expectation": scenario["expectation"],
                "actual": actual,
                "evidence": evidence,
                "status": status,
            }
        )

    git_clean = not manifest["git"]["dirty"]
    admitted = all_scenarios_passed and protected_unchanged and git_clean
    verdict = "ДОПУСТИТЬ" if admitted else "НЕ ДОПУСКАТЬ"
    report = {
        "run_id": manifest["run_id"],
        "git_commit": manifest["git"]["commit"],
        "git_clean": git_clean,
        "protected_archive_unchanged": protected_unchanged,
        "scenarios": rows,
        "verdict": verdict,
    }
    write_json(run_dir / "report.json", report)

    markdown = [
        "# Отчёт приёмочных испытаний",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Git commit: `{manifest['git']['commit']}`",
        f"- Чистая рабочая копия: `{'да' if git_clean else 'нет'}`",
        f"- Защищённые файлы архива неизменны: `{'да' if protected_unchanged else 'нет'}`",
        f"- Итоговый вердикт: **{verdict}**",
        "",
        "| ID | Сценарий | Ожидание | Фактический результат | Доказательство | Итог |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        evidence_text = "<br>".join(f"`{item}`" for item in row["evidence"])
        markdown.append(
            f"| {row['id']} | {row['name']} | {row['expectation']} | "
            f"{row['actual']} | {evidence_text} | **{row['status']}** |"
        )
    markdown.extend(
        [
            "",
            "## Правило допуска",
            "",
            "`PENDING_MANUAL`, `FAILED`, `BLOCKED`, изменённый защищённый архив или грязная рабочая копия автоматически дают вердикт «НЕ ДОПУСКАТЬ».",
            "",
        ]
    )
    (run_dir / "REPORT.md").write_text("\n".join(markdown), encoding="utf-8")
    logger.info("Acceptance report updated: verdict=%s report=%s", verdict, run_dir / "REPORT.md")
    print(run_dir / "REPORT.md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-oriented acceptance test runner")
    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser("start", help="Создать прогон и выполнить безопасную автоматическую часть")
    start.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    start.add_argument("--config", type=Path, required=True)

    request = subparsers.add_parser("request", help="Отправить ручной scan-запрос и сохранить доказательства")
    request.add_argument("--run", required=True)
    request.add_argument("--scenario", required=True, type=int, choices=range(1, 13))
    request.add_argument("--task-id", required=True)
    request.add_argument("--doc-type", required=True)
    request.add_argument("--document-number", required=True)
    request.add_argument("--scanner-profile", required=True)
    request.add_argument("--idempotency-key")
    request.add_argument("--url")
    request.add_argument("--timeout", type=float, default=360.0)
    request.add_argument("--confirm-real-scan", action="store_true")

    record = subparsers.add_parser("record", help="Зафиксировать результат ручного сценария")
    record.add_argument("--run", required=True)
    record.add_argument("--scenario", required=True, type=int, choices=range(1, 13))
    record.add_argument("--status", required=True, choices=["PASSED", "FAILED", "BLOCKED"])
    record.add_argument("--notes", required=True)
    record.add_argument("--evidence", action="append")

    finalize = subparsers.add_parser("finalize", help="Пересчитать хэши и сформировать итоговый отчёт")
    finalize.add_argument("--run", required=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "start"
    if command == "start":
        if not hasattr(args, "config"):
            parser.error("start requires --config")
        run_dir = start_run(getattr(args, "runs_root", DEFAULT_RUNS_ROOT), args.config)
        print(f"Acceptance evidence: {run_dir}")
    elif command == "request":
        request_scan(args)
    elif command == "record":
        record_manual(args)
    elif command == "finalize":
        run_dir, manifest = validate_run_dir(args.run)
        finalize_run(run_dir, manifest)
    else:
        parser.error(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
