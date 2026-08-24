from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_patterns import PATTERN_SOURCE


def test_general_patterns_execute_in_native_rust(tmp_path: Path) -> None:
    source = tmp_path / "patterns.py"
    source.write_text(
        PATTERN_SOURCE
        + """
print(literal_or_range(1))
print(literal_or_range(5))
print(literal_or_range(9))
print(guarded_option(9, 5))
print(guarded_option(3, 5))
print(guarded_option(None, 5))
print(point_total(0, 7))
print(point_total(4, 4))
print(point_total(3, 4))
print(nested_shape_total(0, 8))
print(nested_shape_total(3, 5))
print(tuple_rest(2, 9))
print(tuple_loop_total())
print(hygienic_tuple(7, "x"))
print(hygienic_tuple(7, "y"))
print(hygienic_field(9))
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
        "10",
        "5",
        "0",
        "9",
        "5",
        "0",
        "7",
        "8",
        "7",
        "8",
        "8",
        "11",
        "10",
        "7",
        "0",
        "9",
    ]
