from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_closure_contracts import CLOSURE_CONTRACT_SOURCE


@capability_contract("closures.capture-contracts", native=True)
def test_explicit_move_closure_block_runs_natively(tmp_path: Path) -> None:
    source = tmp_path / "closures.py"
    source.write_text(
        CLOSURE_CONTRACT_SOURCE
        + """
values = rust.Vec[rust.u64]([1, 2, 3])
print(transform(values, 10))
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
    assert result.stdout.splitlines() == ["1", "2", "3", "[11, 12, 13]"]
