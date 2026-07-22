from __future__ import annotations

import json

from app.configuration import apply_configuration
from app.production_config import validate_runtime_environment


def build_preflight_report() -> dict[str, object]:
    config = validate_runtime_environment()
    return {
        "status": "ok",
        "environment": config.environment,
        "production": config.production,
        "archive_root": str(config.archive_root.resolve(strict=False)),
        "incoming_dir": str(config.incoming_dir.resolve(strict=False)),
        "allowed_doc_types": sorted(config.allowed_doc_types),
        "document_year_range": [
            config.min_document_year,
            config.max_document_year,
        ],
        "note": "No scanner was started and no archive file was written.",
    }


def main() -> None:
    applied = apply_configuration()
    report = build_preflight_report()
    report["config_path"] = str(applied.path) if applied.loaded else None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
