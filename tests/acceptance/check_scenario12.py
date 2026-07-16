from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from tests.acceptance.run_acceptance_tests import (
    read_json,
    sha256,
    snapshot_files,
    validate_run_dir,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify acceptance scenario 12 evidence")
    parser.add_argument("--run", required=True)
    args = parser.parse_args()

    run_dir, manifest = validate_run_dir(args.run)
    attempts_root = run_dir / "scenario_12" / "manual_attempts"
    attempts: list[dict[str, Any]] = []
    for attempt_dir in sorted(path for path in attempts_root.iterdir() if path.is_dir()):
        response = read_json(attempt_dir / "response.json")
        request = read_json(attempt_dir / "input.json")
        attempts.append(
            {
                "directory": str(attempt_dir.relative_to(run_dir)),
                "request": request,
                "response": response,
            }
        )

    expected_tasks = {f"ACC-012-{index:03d}" for index in range(1, 21)}
    successful = [
        item
        for item in attempts
        if item["response"].get("http_status") == 200
        and (item["response"].get("json") or {}).get("status") == "succeeded"
        and item["request"].get("task_id") in expected_tasks
    ]
    rejected = [item for item in attempts if item not in successful]
    success_by_task = {item["request"]["task_id"]: item for item in successful}

    archive = Path(manifest["test_environment"]["archive"])
    incoming = Path(manifest["test_environment"]["incoming"])
    records = Path(manifest["test_environment"]["idempotency"])
    server_logs = Path(manifest["test_environment"]["server_logs"])
    current_archive = snapshot_files(archive)
    current_by_path = {item["path"]: item for item in current_archive}

    if not attempts:
        raise SystemExit("Scenario 12 has no saved attempts")
    baseline_attempt = run_dir / attempts[0]["directory"]
    baseline = read_json(baseline_attempt / "archive_before.json")
    baseline_by_path = {item["path"]: item for item in baseline}
    baseline_unchanged = all(current_by_path.get(path) == item for path, item in baseline_by_path.items())
    created = [item for path, item in current_by_path.items() if path not in baseline_by_path]

    file_results: list[dict[str, Any]] = []
    for task_id in sorted(expected_tasks):
        item = success_by_task.get(task_id)
        if item is None:
            file_results.append({"task_id": task_id, "ok": False, "error": "missing_success"})
            continue
        response_json = item["response"].get("json") or {}
        file_name = response_json.get("file_name")
        matches = [path for path in archive.rglob(file_name) if path.is_file()] if file_name else []
        if len(matches) != 1:
            file_results.append(
                {"task_id": task_id, "file_name": file_name, "ok": False, "error": f"matches={len(matches)}"}
            )
            continue
        path = matches[0]
        try:
            page_count = len(PdfReader(str(path), strict=True).pages)
            pdf_error = None
        except Exception as exc:
            page_count = None
            pdf_error = f"{type(exc).__name__}: {exc}"
        file_results.append(
            {
                "task_id": task_id,
                "operation_id": response_json.get("operation_id"),
                "idempotency_key": response_json.get("idempotency_key"),
                "file_name": file_name,
                "path": str(path.relative_to(archive)),
                "size": path.stat().st_size,
                "sha256": sha256(path),
                "page_count": page_count,
                "scan_executed": response_json.get("scan_executed"),
                "ok": page_count is not None and page_count >= 1 and response_json.get("scan_executed") is True,
                "error": pdf_error,
            }
        )

    names = [item.get("file_name") for item in file_results if item.get("file_name")]
    operations = [item.get("operation_id") for item in file_results if item.get("operation_id")]
    keys = [item.get("idempotency_key") for item in file_results if item.get("idempotency_key")]

    log_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(server_logs.glob("*.txt"))
    )
    log_links = [
        {
            "task_id": item.get("task_id"),
            "operation_id": item.get("operation_id"),
            "file_name": item.get("file_name"),
            "task_found": str(item.get("task_id")) in log_text,
            "operation_found": str(item.get("operation_id")) in log_text,
            "file_found": str(item.get("file_name")) in log_text,
        }
        for item in file_results
    ]

    idempotency_records = []
    for path in sorted(records.glob("*.json")):
        data = read_json(path)
        if data.get("task_id") in expected_tasks:
            idempotency_records.append(data)
    records_by_task = {item.get("task_id"): item for item in idempotency_records}

    protected_before = read_json(run_dir / "protected_before.json")
    protected_after = snapshot_files(archive / "_protected")
    lock_files = list(incoming.rglob(".scanner.lock"))
    incoming_pdfs = list(incoming.glob("PF_*.pdf"))
    leftovers = list(archive.rglob("*.tmp")) + list(archive.rglob("*.reserve"))

    checks = {
        "twenty_successful_tasks": len(successful) == 20 and set(success_by_task) == expected_tasks,
        "one_result_per_task": len(successful) == len(success_by_task),
        "twenty_new_archive_files": len(created) == 20,
        "baseline_archive_unchanged": baseline_unchanged,
        "all_pdfs_valid": all(item.get("ok") for item in file_results),
        "unique_file_names": len(names) == 20 and len(set(names)) == 20,
        "unique_operation_ids": len(operations) == 20 and len(set(operations)) == 20,
        "unique_idempotency_keys": len(keys) == 20 and len(set(keys)) == 20,
        "all_log_links_present": all(
            item["task_found"] and item["operation_found"] and item["file_found"] for item in log_links
        ),
        "all_idempotency_succeeded": all(
            records_by_task.get(task_id, {}).get("status") == "succeeded" for task_id in expected_tasks
        ),
        "no_scanner_lock": not lock_files,
        "incoming_empty": not incoming_pdfs,
        "no_archive_leftovers": not leftovers,
        "protected_archive_unchanged": protected_before == protected_after,
    }
    passed = all(checks.values())
    result = {
        "passed": passed,
        "checks": checks,
        "successful_request_count": len(successful),
        "rejected_attempts": [
            {
                "directory": item["directory"],
                "task_id": item["request"].get("task_id"),
                "http_status": item["response"].get("http_status"),
                "error_code": (item["response"].get("json") or {}).get("error_code"),
            }
            for item in rejected
        ],
        "created_archive_files": created,
        "files": file_results,
        "log_links": log_links,
        "idempotency_records": idempotency_records,
        "lock_files": [str(path) for path in lock_files],
        "incoming_pdfs": [str(path) for path in incoming_pdfs],
        "archive_leftovers": [str(path) for path in leftovers],
    }
    output = run_dir / "scenario_12" / "verification.json"
    write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
