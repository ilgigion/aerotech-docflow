from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.scanner_recovery import cleanup_archive_artifacts, recover_stale_lock_if_safe
from tests.acceptance.run_acceptance_tests import (
    finalize_run,
    read_json,
    snapshot_files,
    validate_run_dir,
    write_json,
)


STAGES = ("after_temp_copy", "during_copy", "after_publish")
EXPECTED_EXIT_CODES = {"after_temp_copy": 90, "during_copy": 91, "after_publish": 92}


def execute_worker(root: Path, case_id: str, stage: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.acceptance.scenario10_worker",
            "--root",
            str(root),
            "--case-id",
            case_id,
            "--stage",
            stage,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled crash probes for acceptance scenario 10")
    parser.add_argument("--run", required=True)
    parser.add_argument("--label", default="controlled_crash_probes_v3")
    args = parser.parse_args()

    run_dir, manifest = validate_run_dir(args.run)
    evidence_root = run_dir / "scenario_10" / args.label
    evidence_root.mkdir(parents=True, exist_ok=True)
    scenario_06_result_path = run_dir / "scenario_06" / "manual_result.json"
    scenario_06_result = read_json(scenario_06_result_path) if scenario_06_result_path.exists() else None
    results: dict[str, object] = {
        "real_scan_stage": {
            "covered_by": "scenario_06/manual_result.json",
            "passed": bool(scenario_06_result and scenario_06_result.get("status") == "PASSED"),
        }
    }

    for index, stage in enumerate(STAGES, start=1):
        case_id = f"{index}-{stage}"
        root = evidence_root / stage
        if root.exists() and any(root.iterdir()):
            raise SystemExit(f"Evidence directory is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)

        crashed = execute_worker(root, case_id, stage)
        (root / "crash_process.log").write_text(crashed.stdout, encoding="utf-8")
        before_recovery = {
            "worker_exit_code": crashed.returncode,
            "expected_exit_code": EXPECTED_EXIT_CODES[stage],
            "files": snapshot_files(root),
        }
        write_json(root / "before_recovery.json", before_recovery)

        lock_result = recover_stale_lock_if_safe(root / "incoming", stale_after_seconds=0)
        removed_artifacts = cleanup_archive_artifacts(root / "archive")
        recovery = {
            "lock_existed": lock_result.lock_existed,
            "lock_removed": lock_result.removed,
            "lock_reason": lock_result.reason,
            "removed_archive_artifacts": [str(path) for path in removed_artifacts],
        }
        write_json(root / "recovery.json", recovery)

        retry = execute_worker(root, case_id, "retry")
        (root / "retry_process.log").write_text(retry.stdout, encoding="utf-8")
        after_retry_files = snapshot_files(root)
        write_json(root / "after_retry.json", after_retry_files)

        final_pdfs = [item for item in after_retry_files if item["path"].startswith("archive/") and item["path"].endswith(".pdf")]
        incoming_pdfs = [item for item in after_retry_files if item["path"].startswith("incoming/") and item["path"].endswith(".pdf")]
        leftovers = [item for item in after_retry_files if item["path"].endswith((".tmp", ".reserve", ".lock"))]
        passed = (
            crashed.returncode == EXPECTED_EXIT_CODES[stage]
            and (root / "crash_marker.json").exists()
            and retry.returncode == 0
            and len(final_pdfs) == 1
            and not incoming_pdfs
            and not leftovers
        )
        results[stage] = {
            "passed": passed,
            "crash_exit_code": crashed.returncode,
            "retry_exit_code": retry.returncode,
            "final_pdfs": final_pdfs,
            "incoming_pdfs": incoming_pdfs,
            "leftovers": leftovers,
            "evidence": str(root.relative_to(run_dir)),
        }

    overall_passed = all(bool(value.get("passed")) for value in results.values() if isinstance(value, dict))
    results["overall_passed"] = overall_passed
    write_json(evidence_root / "summary.json", results)
    finalize_run(run_dir, manifest)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise SystemExit(0 if overall_passed else 1)


if __name__ == "__main__":
    main()
