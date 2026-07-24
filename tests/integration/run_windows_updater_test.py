from __future__ import annotations

import argparse
import json
import os

from updater.transaction import read_version_file
from updater.windows import UpdaterPaths, process_names, service_state


parser = argparse.ArgumentParser(
    description="Read-only inspection of an installed Aerotech Docflow updater environment."
)
parser.add_argument(
    "--confirm-read-only-production-check",
    action="store_true",
    help="Acknowledge that canonical production paths and service state will be read.",
)
args = parser.parse_args()
if not args.confirm_read_only_production_check:
    raise SystemExit("Pass --confirm-read-only-production-check. No files will be changed.")
if os.name != "nt":
    raise SystemExit("Windows is required.")

paths = UpdaterPaths.production()
version = read_version_file(paths.install_dir / "version.json")
report = {
    "install_dir": str(paths.install_dir),
    "updater_dir": str(paths.updater_dir),
    "config_exists": paths.config_path.is_file(),
    "installed_version": str(version.version),
    "config_schema": version.config_schema,
    "service_state": service_state(),
    "naps2_processes": [name for name in process_names() if name.casefold().startswith("naps2")],
    "note": "Read-only check; no update was started.",
}
print(json.dumps(report, ensure_ascii=False, indent=2))
