from __future__ import annotations

import re
from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import Effect
from crabwalk.diagnostics import CrabwalkCompilationError


FILESYSTEM_RESULT_SOURCE = """\
from crabwalk import CrabwalkRustError, rust

@rust.fn
def read_username_from_file(
    path: rust.Str,
) -> rust.Result[rust.String, rust.IoError]:
    username_file: rust.File = rust.try_(rust.File.open(path))
    username: rust.String = rust.try_(username_file.read_to_string())
    return rust.Ok(username)
"""


def test_file_io_result_propagation_lowers_to_native_question_mark(
    tmp_path: Path,
) -> None:
    source = tmp_path / "filesystem_result.py"
    source.write_text(FILESYSTEM_RESULT_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_filesystem_result")
    function = ir.functions[0]
    rust_source = generated.rust_source

    assert Effect.BLOCKING in function.effects
    assert "-> Result<String, std::io::Error>" in rust_source
    assert re.search(
        r"let mut username_file: std::fs::File = "
        r"std::fs::File::open\(path\)\?;",
        rust_source,
    )
    assert "std::io::Read::read_to_string(&mut username_file" in rust_source
    assert re.search(r"\.map\(\|_\| __cw_tmp_\d+_[0-9a-f]+\) \}\?;", rust_source)
    assert '"rust.IoError", error.to_string()' in rust_source
    assert "std::fs::File::open(path).unwrap()" not in rust_source
    assert "read_to_string(&mut username_file" in rust_source
    assert "read_to_string(&mut username_file).unwrap()" not in rust_source


@pytest.mark.parametrize(
    ("function_source", "title"),
    (
        (
            """\
@rust.fn
def invalid(path: rust.Str) -> rust.String:
    return rust.try_(rust.File.open(path)).read_to_string().unwrap()
""",
            "Rust try requires a Result-returning function",
        ),
        (
            """\
@rust.fn
def invalid(path: rust.Str) -> rust.Result[rust.String, rust.String]:
    file: rust.File = rust.try_(rust.File.open(path))
    return rust.Ok(file.read_to_string().unwrap())
""",
            "Rust try error types differ",
        ),
    ),
)
def test_try_rejects_an_unrepresentable_propagation_contract(
    tmp_path: Path,
    function_source: str,
    title: str,
) -> None:
    source = tmp_path / "invalid_try.py"
    source.write_text(
        "from crabwalk import rust\n\n" + function_source,
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB177"
    assert diagnostic.title == title
