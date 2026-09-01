from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_integral_operators import INTEGRAL_OPERATOR_SOURCE


@capability_contract("compiler.integral-bitwise")
def test_integral_bitwise_operators_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "native_integral_operators.py"
    source.write_text(
        INTEGRAL_OPERATOR_SOURCE
        + """
print(breakpoint_before_enabled(3))
print(breakpoint_before_enabled(2))
print(bitwise_pipeline(8))
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
    assert result.stdout.splitlines() == ["True", "False", "11"]
