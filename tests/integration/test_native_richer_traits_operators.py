from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_richer_traits_operators import RICH_TRAIT_SOURCE


@capability_contract("traits.arguments-receivers-associated", native=True)
def test_trait_arguments_receiver_modes_and_subtraction_run_natively(
    tmp_path: Path,
) -> None:
    source = tmp_path / "richer_traits.py"
    source.write_text(
        RICH_TRAIT_SOURCE + "\nprint(richer_trait_demo())\n",
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
    assert result.stdout.splitlines() == ["1750"]
