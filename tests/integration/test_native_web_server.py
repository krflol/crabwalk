from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_web_server import WEB_SERVER_SOURCE


@capability_contract("threadpool.loopback-http")
def test_loopback_http_and_thread_pool_execute_natively(tmp_path: Path) -> None:
    source = tmp_path / "web_server.py"
    source.write_text(
        WEB_SERVER_SOURCE
        + """
ok = http_round_trip("/")
missing = http_round_trip("/missing")
slow = http_round_trip("/sleep")
print(ok.startswith("HTTP/1.1 200 OK"), "Hi from Rust" in ok)
print(missing.startswith("HTTP/1.1 404 NOT FOUND"), "Oops!" in missing)
print(slow.startswith("HTTP/1.1 200 OK"))
print(thread_pool_jobs())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "True True",
        "True True",
        "True",
        "3",
    ]
