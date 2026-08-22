from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_book_foundations import BOOK_FOUNDATIONS


def test_book_foundations_compile_and_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "book_foundations.py"
    source.write_text(
        BOOK_FOUNDATIONS
        + "\nprint(binding_rules())\n"
        + "print(tuple_and_array())\n"
        + "print(echo_character('🦀'))\n"
        + "print(echo_character('x'))\n",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["10806", "515", "🦀", "x"]
