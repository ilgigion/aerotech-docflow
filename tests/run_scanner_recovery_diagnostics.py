from pathlib import Path
import argparse
import json

from app.scanner_recovery import (
    diagnose_scanner_state,
    emergency_recover_after_interruption,
)


def print_report(incoming_dir: Path, archive_root: Path) -> None:
    report = diagnose_scanner_state(incoming_dir, archive_root)

    print()
    print("SCANNER DIAGNOSTICS")
    print(f"incoming_dir: {report.incoming_dir}")
    print(f"archive_root: {report.archive_root}")

    print()
    print(f"lock_exists: {report.lock_exists}")
    print(f"lock_info: {json.dumps(report.lock_info, ensure_ascii=False, indent=2) if report.lock_info else None}")

    print()
    print("NAPS2 processes:")
    if report.naps2_processes:
        for process in report.naps2_processes:
            print(f"  PID={process.pid} IMAGE={process.image_name} MEM={process.memory_usage}")
    else:
        print("  none")

    print()
    print("Incoming PF_*.pdf files:")
    if report.incoming_pf_files:
        for path in report.incoming_pf_files[:20]:
            print(f"  {path}")
    else:
        print("  none")

    print()
    print("Archive *.tmp files:")
    if report.archive_tmp_files:
        for path in report.archive_tmp_files[:20]:
            print(f"  {path}")
    else:
        print("  none")

    print()
    print("Archive *.reserve files:")
    if report.archive_reserve_files:
        for path in report.archive_reserve_files[:20]:
            print(f"  {path}")
    else:
        print("  none")

    print()
    print(f"has_risk_markers: {report.has_risk_markers}")


parser = argparse.ArgumentParser()
parser.add_argument("--incoming", default=r"D:\incoming")
parser.add_argument("--archive", default=r"D:\archive_test")
parser.add_argument("--kill-naps2", action="store_true")
parser.add_argument("--remove-lock", action="store_true")
parser.add_argument("--cleanup-artifacts", action="store_true")
args = parser.parse_args()

incoming_dir = Path(args.incoming)
archive_root = Path(args.archive)

print_report(incoming_dir, archive_root)

if args.kill_naps2 or args.remove_lock or args.cleanup_artifacts:
    print()
    print("RECOVERY ACTIONS")
    result = emergency_recover_after_interruption(
        incoming_dir=incoming_dir,
        archive_root=archive_root,
        kill_naps2=args.kill_naps2,
        remove_lock=args.remove_lock,
        cleanup_artifacts=args.cleanup_artifacts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print_report(incoming_dir, archive_root)
