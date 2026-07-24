from pathlib import Path
from tempfile import TemporaryDirectory

import tests.acceptance.run_acceptance_tests as acceptance


captured: dict[str, object] = {}


class FakeClient:
    def __init__(self, **kwargs):
        captured["client_kwargs"] = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback

    def post(self, url, *, json):
        captured["url"] = url
        captured["payload"] = json
        return object()


original_client = acceptance.httpx.Client
acceptance.httpx.Client = FakeClient
try:
    result = acceptance.post_local_scan_request(
        "http://127.0.0.1:8000/scan",
        {"task_id": "TEST"},
        12.5,
    )
finally:
    acceptance.httpx.Client = original_client

assert result is not None
assert captured["client_kwargs"] == {"trust_env": False, "timeout": 12.5}
assert captured["url"] == "http://127.0.0.1:8000/scan"

with TemporaryDirectory() as temp_dir:
    run_dir = Path(temp_dir)
    acceptance.create_scenario12_script(run_dir, "http://127.0.0.1:8000/health")
    script = (run_dir / "scenario_12" / "run_20_documents.ps1").read_bytes()
    script.decode("ascii")
    text = script.decode("ascii")
    assert "Type SCAN to start" in text
    assert 'if ($confirmation -ieq "SCAN")' in text
    assert "[int]$StartAt = 1" in text
    assert "[string]$ScannerProfile" in text
    assert "--scanner-profile $ScannerProfile" in text

print("OK: acceptance runner ignores proxies and generates guarded series script")
