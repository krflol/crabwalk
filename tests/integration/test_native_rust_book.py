from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_completed_rust_book_chapters_run_as_one_native_package() -> None:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(root / "src"), str(root / "examples"))
    )
    environment["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, "-u", "-m", "th_rust_book.run_all"],
        cwd=root / "examples",
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "Hello, world!",
        "Rust Book chapters 1-21: all native assertions passed",
    ]
