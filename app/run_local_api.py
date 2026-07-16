from __future__ import annotations

import uvicorn

from app.production_config import validate_runtime_environment


def main() -> None:
    validate_runtime_environment()
    uvicorn.run("app.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
