from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_native_etl_pipeline import NATIVE_ETL_SOURCE


@capability_contract(
    "etl.native-standard-library",
    "etl.ordered-grouping",
    native=True,
)
def test_parse_validate_group_sort_format_and_emit_remains_native(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "rows.txt"
    input_path.write_text(
        "beta|active|5\nalpha|active|3\nbeta|active|7\nignored|inactive|99\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "output.txt"
    source = tmp_path / "native_etl.py"
    source.write_text(
        NATIVE_ETL_SOURCE
        + f"""
value = native_etl({str(input_path)!r}, {str(output_path)!r})
assert value > 0
assert directory_entries({str(tmp_path)!r}) >= 3
print({str(output_path)!r})
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
    assert output_path.read_text(encoding="utf-8") == ("alpha|3\nbeta|12\nscale|1.25\n")
