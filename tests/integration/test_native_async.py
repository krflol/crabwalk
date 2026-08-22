from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_async_native import ASYNC_SOURCE


def test_native_async_helpers_compile_and_run_through_block_on(
    tmp_path: Path,
) -> None:
    source = tmp_path / "async_native.py"
    source.write_text(
        ASYNC_SOURCE
        + "\nprint(run_pipeline(5))\n"
        + "print(run_joined_total())\n"
        + "print(run_selected_value())\n"
        + "print(run_channel_total())\n",
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
    assert result.stdout.splitlines() == ["20", "7", "20", "30"]
