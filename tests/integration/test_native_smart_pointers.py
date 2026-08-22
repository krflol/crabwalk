from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_smart_pointers import SMART_POINTER_SOURCE


def test_box_rc_and_refcell_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "smart_pointers.py"
    source.write_text(
        SMART_POINTER_SOURCE
        + "\nprint(boxed_value(42))\n"
        + "print(rc_counts())\n"
        + "print(interior_mutation())\n",
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
    assert result.stdout.splitlines() == ["42", "21", "15"]
