from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_filesystem_results import FILESYSTEM_RESULT_SOURCE


@capability_contract("filesystem.result-propagation")
def test_native_file_io_preserves_success_open_error_and_read_error(
    tmp_path: Path,
) -> None:
    username = tmp_path / "username.txt"
    username.write_bytes(b"Ferris\n")
    missing = tmp_path / "missing.txt"
    invalid_utf8 = tmp_path / "invalid-utf8.txt"
    invalid_utf8.write_bytes(b"\xff")
    source = tmp_path / "filesystem_result.py"
    source.write_text(
        FILESYSTEM_RESULT_SOURCE
        + f"""
print(repr(read_username_from_file({str(username)!r})))
try:
    read_username_from_file({str(missing)!r})
except CrabwalkRustError as error:
    print(type(error).__name__, error.variant, error.source_chain[0].rust_type)
try:
    read_username_from_file({str(invalid_utf8)!r})
except CrabwalkRustError as error:
    print(type(error).__name__, error.variant, error.source_chain[0].rust_type)
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
        "'Ferris\\n'",
        "CrabwalkRustError Io rust.IoError",
        "CrabwalkRustError Io rust.IoError",
    ]
