from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_methods_traits import METHOD_TRAIT_SOURCE


@capability_contract("traits.dynamic-dispatch")
def test_inherent_methods_and_dynamic_dispatch_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "methods_traits.py"
    source.write_text(
        METHOD_TRAIT_SOURCE + "\nprint(method_and_trait_demo())\n",
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
    assert result.stdout.splitlines() == ["31"]
