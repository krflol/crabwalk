from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract


SOURCE = """\
from crabwalk import rust

@rust.fn
def total(values: rust.HashMap[rust.String, rust.u64]) -> rust.u64:
    return values.values().copied().sum()

@rust.fn
def byte_key_total(values: rust.HashMap[rust.Vec[rust.u8], rust.u64]) -> rust.u64:
    return values.values().copied().sum()

print(total({"active": 2, "pending": 3}))
print(byte_key_total({b"active": 7, b"pending": 4}))
try:
    total({"active": True})
except TypeError as error:
    print("mapping value for key 'active'" in str(error))
"""


@capability_contract("structured.hashmap-input")
def test_python_mapping_crosses_checked_hashmap_boundary(tmp_path: Path) -> None:
    source = tmp_path / "hashmap_input.py"
    source.write_text(SOURCE, encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

    completed = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == ["5", "11", "True"]
