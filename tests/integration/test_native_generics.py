from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_generics import GENERIC_SOURCE


@capability_contract("generics.concrete-export")
def test_generic_helper_compiles_and_runs_through_a_concrete_export(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generics.py"
    source.write_text(
        GENERIC_SOURCE
        + "\nprint(largest_u64())\n"
        + "print(longest_owned('abcd', 'xyz'))\n",
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
    assert result.stdout.splitlines() == ["100", "abcd"]
