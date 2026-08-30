from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_call_ergonomics import CALL_ERGONOMICS_SOURCE


@capability_contract("calls.keywords-defaults")
def test_exported_keywords_and_defaults_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "native_calls.py"
    source.write_text(
        CALL_ERGONOMICS_SOURCE
        + """
print(adjusted(5))
print(adjusted(value=5))
print(adjusted(5, increment=3))
print(adjusted(increment=3, value=5))
print(internal_keyword(), internal_default())
for call in (
    lambda: adjusted(),
    lambda: adjusted(1, value=2),
    lambda: adjusted(1, unknown=2),
):
    try:
        call()
    except TypeError as error:
        print(type(error).__name__)
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
        "7",
        "7",
        "8",
        "8",
        "7 7",
        "TypeError",
        "TypeError",
        "TypeError",
    ]
