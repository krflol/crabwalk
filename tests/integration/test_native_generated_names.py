from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_colliding_source_names_execute_through_isolated_native_symbols(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native_names.py"
    source.write_text(
        r"""from crabwalk import rust

pyo3 = rust.crate("regex", version="1")

@rust.struct
class String:
    value: rust.u64

@rust.fn
def abs(value: rust.i32) -> rust.i32:
    return value

@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return pyo3.Regex.new(r"\d+").unwrap().is_match(value)

print(abs(-7))
print(contains_number("item 42"))
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
    assert result.stdout.splitlines() == ["-7", "True"]


def test_rust_keywords_prelude_names_and_compiler_prefixes_are_hygienic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native_binding_identities.py"
    source.write_text(
        """\
from crabwalk import rust

String = rust.typevar("String")

@rust.generic(String, bounds=[rust.Copy])
def generic(Ok: String) -> String:
    return Ok

@rust.fn
def identity(self: rust.u64) -> rust.u64:
    __cw_result: rust.u64 = self
    values: rust.Vec[rust.u64] = rust.Vec([__cw_result])
    normalized: rust.u64 = values.iter().map(lambda gen: gen).sum()
    match normalized:
        case Ok:
            return generic(Ok)

print(identity(41))
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
    assert result.stdout.splitlines() == ["41"]
