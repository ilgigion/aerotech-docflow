from __future__ import annotations

import json

from app.production_config import validate_runtime_environment


def main() -> None:
    config = validate_runtime_environment()
    print(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
