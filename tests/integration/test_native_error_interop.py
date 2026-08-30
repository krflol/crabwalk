from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_error_interop import ERROR_INTEROP_SOURCE


@capability_contract("errors.from-structured")
def test_native_declared_from_conversions_preserve_structured_error_causes(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.txt"
    valid.write_text("42\n", encoding="utf-8")
    invalid = tmp_path / "invalid.txt"
    invalid.write_text("not-a-number\n", encoding="utf-8")
    zero = tmp_path / "zero.txt"
    zero.write_text("0\n", encoding="utf-8")
    missing = tmp_path / "missing.txt"
    source = tmp_path / "error_interop.py"
    source.write_text(
        ERROR_INTEROP_SOURCE
        + f"""
assert load_nonzero({str(valid)!r}) == 42

def capture(path):
    try:
        load_nonzero(path)
    except CrabwalkRustError as error:
        return (
            error.variant,
            error.fields,
            [(item.rust_type, item.message) for item in error.source_chain],
        )
    raise AssertionError("expected CrabwalkRustError")

missing_error = capture({str(missing)!r})
assert missing_error[0] == "Io", missing_error
assert set(missing_error[1]) == {{"source"}}, missing_error
assert missing_error[2][0][0] == "rust.IoError", missing_error

parse_error = capture({str(invalid)!r})
assert parse_error[0] == "Parse", parse_error
assert set(parse_error[1]) == {{"source"}}, parse_error
assert parse_error[2][0][0] == "rust.String", parse_error

validation_error = capture({str(zero)!r})
assert validation_error == (
    "Validation",
    {{"message": "value must be nonzero"}},
    [],
), validation_error
print("structured-errors-ok")
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
    assert result.stdout.splitlines() == ["structured-errors-ok"]
