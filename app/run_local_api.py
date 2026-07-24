from __future__ import annotations

import os

import uvicorn

from app.configuration import apply_configuration
from app.production_config import validate_runtime_environment


def main(*, configuration_already_applied: bool = False) -> None:
    if not configuration_already_applied:
        apply_configuration()
    validate_runtime_environment()
    host = os.getenv("DOCFLOW_HOST", "").strip()
    if not host:
        raise ValueError("DOCFLOW_HOST is empty; set application.host in config.toml")
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("DOCFLOW_HOST must remain 127.0.0.1 or localhost")
    try:
        port = int(os.environ["DOCFLOW_PORT"])
    except KeyError as exc:
        raise ValueError("DOCFLOW_PORT is empty; set application.port in config.toml") from exc
    except ValueError as exc:
        raise ValueError("DOCFLOW_PORT must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("DOCFLOW_PORT must be in 1..65535")
    uvicorn.run("app.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
