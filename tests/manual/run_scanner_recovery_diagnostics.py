from pathlib import Path
import argparse
import json

from app.scanner_recovery import (
    diagnose_scanner_state,
    emergency_recover_after_interruption,
)


def print_paths(title: str, paths: list[Path], limit: int = 20) -> None:
    print()
    print(title)
    if paths:
        for path in paths[:limit]:
            print(f"  {path}")
    else:
        print("  none")


def print_report(incoming_dir: Path, archive_root: Path, stale_after_seconds: int) -> None:
    report = diagnose_scanner_state(
        incoming_dir,
        archive_root,
        lock_stale_after_seconds=stale_after_seconds,
    )

    print()
    print("SCANNER DIAGNOSTICS")
    print(f"incoming_dir: {report.incoming_dir}")
    print(f"archive_root: {report.archive_root}")
    print(f"stale_after_seconds: {stale_after_seconds}")

    print()
    print(f"lock_exists: {report.lock_exists}")
    print(f"lock_is_stale: {report.lock_is_stale}")
    print(f"lock_info: {json.dumps(report.lock_info, ensure_ascii=False, indent=2) if report.lock_info else None}")

    print()
    print("NAPS2 processes:")
    if report.naps2_processes:
        for process in report.naps2_processes:
            print(f"  PID={process.pid} IMAGE={process.image_name} MEM={process.memory_usage}")
    else:
        print("  none")

    print_paths("Incoming PF_*.pdf files:", report.incoming_pf_files)
    print_paths("Incoming _failed_runtime files:", report.incoming_failed_runtime_files)
    print_paths("Archive *.tmp files:", report.archive_tmp_files)
    print_paths("Archive *.reserve files:", report.archive_reserve_files)

    print()
    print(f"has_risk_markers: {report.has_risk_markers}")


parser = argparse.ArgumentParser()
parser.add_argument("--incoming", default=r"D:\incoming")
parser.add_argument("--archive", default=r"D:\archive_test")
parser.add_argument("--stale-after-seconds", type=int, default=30 * 60)
parser.add_argument("--kill-naps2", action="store_true")
parser.add_argument("--remove-stale-lock", action="store_true")
parser.add_argument("--remove-lock", action="store_true")
parser.add_argument("--cleanup-artifacts", action="store_true")
args = parser.parse_args()

incoming_dir = Path(args.incoming)
archive_root = Path(args.archive)

print_report(incoming_dir, archive_root, args.stale_after_seconds)

if args.kill_naps2 or args.remove_lock or args.remove_stale_lock or args.cleanup_artifacts:
    print()
    print("RECOVERY ACTIONS")
    result = emergency_recover_after_interruption(
        incoming_dir=incoming_dir,
        archive_root=archive_root,
        kill_naps2=args.kill_naps2,
        remove_lock=args.remove_lock,
        remove_stale_lock=args.remove_stale_lock,
        stale_after_seconds=args.stale_after_seconds,
        cleanup_artifacts=args.cleanup_artifacts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print_report(incoming_dir, archive_root, args.stale_after_seconds)
