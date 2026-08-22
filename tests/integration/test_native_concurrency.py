from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_concurrency import CONCURRENCY_SOURCE


def test_threads_channels_and_mutex_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "concurrency.py"
    source.write_text(
        CONCURRENCY_SOURCE
        + "\nprint(moved_vector_length())\n"
        + "print(channel_value())\n"
        + "print(shared_counter())\n",
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
    assert result.stdout.splitlines() == ["3", "42", "1"]
