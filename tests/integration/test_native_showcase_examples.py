from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_structured_etl_showcase_runs_as_documented() -> None:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

    result = subprocess.run(
        [
            sys.executable,
            "-u",
            str(root / "examples" / "showcase" / "structured_etl.py"),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "[('midwest', 16.0), ('west', 7.25)]",
        "structured rows moved=True",
    ]
