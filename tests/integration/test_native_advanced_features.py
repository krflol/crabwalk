from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_advanced_features import ADVANCED_SOURCE


def test_advanced_features_execute_in_native_rust(tmp_path: Path) -> None:
    source = tmp_path / "advanced.py"
    source.write_text(
        ADVANCED_SOURCE
        + """
print(trait_disambiguation_demo())
print(operator_demo())
print(default_generic_operator_demo())
print(unsafe_demo())
print(c_absolute(-42))
print(function_pointer_demo(5))
print(returned_closure_demo(5))
print(heterogeneous_closure_demo(5))
print(associated_item_demo())
print(never_coercion_demo())
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
        "123",
        "46",
        "2500",
        "35",
        "42",
        "12",
        "8",
        "16",
        "9",
        "4",
    ]
