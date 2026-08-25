from __future__ import annotations

import os
import importlib.util
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract


@capability_contract("buffer.readonly-numeric-native")
def test_readonly_numeric_buffer_runs_without_element_copy(tmp_path: Path) -> None:
    source = tmp_path / "native_buffer.py"
    source.write_text(
        """\
from array import array
import json

from crabwalk import rust

@rust.fn
def track_plan(
    durations: rust.Buffer[rust.f64],
) -> rust.Tuple[rust.Vec[rust.f64], rust.f64]:
    offsets: rust.Vec[rust.f64] = rust.Vec([])
    elapsed: rust.f64 = 0.0
    for duration in durations.iter():
        offsets.push(elapsed)
        elapsed += duration
    return offsets, elapsed

@rust.fn
def byte_length(values: rust.Buffer[rust.u8]) -> rust.usize:
    return values.len()

@rust.fn
def consume_with_buffer(
    values: rust.Owned[rust.Vec[rust.u64]],
    durations: rust.Buffer[rust.f64],
) -> rust.usize:
    return values.len() + durations.len()

backing = array("d", [1.5, 2.0, 3.25])
view = memoryview(backing).toreadonly()
print(track_plan(view))
backing[0] = 4.0
print(track_plan(view))
print(json.dumps(track_plan.__crabwalk__["parameter_boundaries"]["durations"], sort_keys=True))
print(track_plan.__crabwalk__["gil_released"])
print([str(value) for value in track_plan.__crabwalk__["effects"]])
print(byte_length(b"crabwalk"))
owned = rust.Vec[rust.u64]([1, 2, 3])
try:
    consume_with_buffer(owned, backing)
except ValueError as error:
    print("read-only" in str(error), owned.moved, rust.to_python(owned))
try:
    import numpy as np
except ImportError:
    print("numpy-unavailable")
else:
    numpy_values = np.array([0.5, 1.0, 1.5], dtype=np.float64)
    numpy_values.flags.writeable = False
    print(track_plan(numpy_values))
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
    assert lines[0] == "([0.0, 1.5, 3.5], 6.75)"
    assert lines[1] == "([0.0, 4.0, 6.0], 9.25)"
    assert '"allocation": "BorrowedBuffer"' in lines[2]
    assert '"borrowed": true' in lines[2]
    assert '"copies_elements": false' in lines[2]
    assert lines[3] == "False"
    assert "BorrowedBuffer" in lines[4]
    assert lines[5] == "8"
    assert lines[6] == "True False [1, 2, 3]"
    if importlib.util.find_spec("numpy") is None:
        assert lines[7] == "numpy-unavailable"
    else:
        assert lines[7] == "([0.0, 0.5, 1.5], 3.0)"
