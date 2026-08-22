from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_closures import CLOSURE_SOURCE


def test_closure_capture_and_iterator_chains_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "closures.py"
    source.write_text(
        CLOSURE_SOURCE + "\nprint(transformed(4, 2))\n" + "print(shifted_sum(3))\n",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

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
    assert result.stdout.splitlines() == ["[4, 5, 6]", "15"]
