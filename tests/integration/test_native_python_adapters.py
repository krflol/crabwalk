from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_python_adapters import PYTHON_ADAPTER_SOURCE


@capability_contract("python-adapter.success-errors")
def test_typed_python_adapter_success_exception_and_invalid_return(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native_python_adapter.py"
    source.write_text(
        PYTHON_ADAPTER_SOURCE
        + """
print(label(7))
print(label.__crabwalk__["gil_released"])
print([str(value) for value in label.__crabwalk__["effects"]])
try:
    fail(9)
except ValueError as error:
    print(type(error).__name__, str(error))
try:
    wrong_type(3)
except TypeError as error:
    print(type(error).__name__, "int" in str(error))
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
    lines = result.stdout.splitlines()
    assert lines[0] == "item-7"
    assert lines[1] == "False"
    assert "PythonRuntime" in lines[2]
    assert "Blocking" in lines[2]
    assert lines[3] == "ValueError bad-9"
    assert lines[4] == "TypeError True"
