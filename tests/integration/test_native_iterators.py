from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_iterators import SEARCH_SOURCE


def test_lines_iterator_and_vec_string_return_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "search.py"
    source.write_text(
        SEARCH_SOURCE
        + """
poem = "Rust:\\nsafe, fast, productive.\\nPick three.\\nTrust me."
print(search("duct", poem))
print(search_case_insensitive("rUsT", poem))
""",
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
    assert result.stdout.splitlines() == [
        "['safe, fast, productive.']",
        "['Rust:', 'Trust me.']",
    ]
