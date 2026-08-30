from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_text_column import TEXT_COLUMN_SOURCE


@capability_contract("text-column.owned-native")
def test_owned_utf8_text_column_runs_natively(tmp_path: Path) -> None:
    source = tmp_path / "native_text_column.py"
    source.write_text(
        TEXT_COLUMN_SOURCE
        + """
data = b"alpha" + "caf\N{LATIN SMALL LETTER E WITH ACUTE}".encode("utf-8")
rows = rust.TextColumn(data, [0, 5, len(data), len(data)])
report = rows.boundary_telemetry
assert report is not None
print(inspect_row(rows, 1, "af"))
print(len(rows), rows.moved)
print(report.boundary_crossings, report.native_container_allocations)
print(report.native_clones, report.bytes_copied)
moved = move_column(rows)
print(rows.moved, moved.moved)
print(rust.to_python(moved))
try:
    rust.TextColumn(b"\\xff", [0, 1])
except UnicodeError as error:
    print("valid UTF-8" in str(error))
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
        "('café', True, 10)",
        "3 False",
        "1 2",
        "0 10",
        "True False",
        "{'data': b'alphacaf\\xc3\\xa9', 'offsets': [0, 5, 10, 10]}",
        "True",
    ]
