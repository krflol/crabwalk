from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_borrowed_returns import BORROWED_RETURN_SOURCE


@capability_contract("ownership.borrowed-return-identity")
def test_borrowed_collection_return_runs_natively(tmp_path: Path) -> None:
    source = tmp_path / "native_borrowed_returns.py"
    source.write_text(
        BORROWED_RETURN_SOURCE + "\nprint(observe_lengths())\n",
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
    assert result.stdout.splitlines() == ["15"]
