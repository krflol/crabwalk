from __future__ import annotations

import re
from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.capabilities import (
    ContractKind,
    capability_contract,
)
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


ERROR_INTEROP_SOURCE = """\
from crabwalk import CrabwalkRustError, rust

@rust.error
class ApplicationError:
    Io = rust.from_error(rust.IoError)
    Parse = rust.from_error(rust.String)
    Validation = rust.variant(message=rust.String)

@rust.fn
def validate(value: rust.u64) -> rust.Result[rust.u64, ApplicationError]:
    if value == 0:
        return rust.Err(ApplicationError.Validation(message="value must be nonzero"))
    return rust.Ok(value)

@rust.fn
def load_nonzero(path: rust.Str) -> rust.Result[rust.u64, ApplicationError]:
    file: rust.File = rust.try_(rust.File.open(path))
    text: rust.String = rust.try_(file.read_to_string())
    parsed: rust.Result[rust.u64, rust.String] = text.trim().parse()
    value: rust.u64 = rust.try_(parsed)
    return validate(value)
"""


def test_declared_error_conversions_lower_to_rust_from_and_question_mark(
    tmp_path: Path,
) -> None:
    source = tmp_path / "error_interop.py"
    source.write_text(ERROR_INTEROP_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_error_interop")
    error = ir.enums[0]

    assert error.is_error
    assert [value.from_source.display() for value in error.variants[:2]] == [
        "rust.IoError",
        "rust.String",
    ]
    assert "impl std::error::Error for" in generated.rust_source
    assert re.search(
        r"impl std::convert::From<std::io::Error> for cw_type_",
        generated.rust_source,
    )
    assert re.search(
        r"impl std::convert::From<String> for cw_type_", generated.rust_source
    )
    assert "std::fs::File::open(path)?" in generated.rust_source
    assert ".parse::<u64>()" in generated.rust_source
    assert "error.__cw_variant()" in generated.rust_source
    assert "error.__cw_sources()" in generated.rust_source


@capability_contract(
    "errors.undeclared-from-rejected",
    native=False,
    kind=ContractKind.NEGATIVE,
)
def test_try_rejects_an_undeclared_error_conversion(tmp_path: Path) -> None:
    source = tmp_path / "missing_conversion.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.error
class ApplicationError:
    Io = rust.from_error(rust.IoError)

@rust.fn
def invalid(text: rust.Str) -> rust.Result[rust.u64, ApplicationError]:
    parsed: rust.Result[rust.u64, rust.String] = text.parse()
    return rust.Ok(rust.try_(parsed))
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB177"
    assert diagnostic.title == "Rust try error types differ"
    assert "no declared From conversion" in diagnostic.message


def test_error_enum_rejects_duplicate_from_sources(tmp_path: Path) -> None:
    source = tmp_path / "duplicate_conversion.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.error
class ApplicationError:
    First = rust.from_error(rust.String)
    Second = rust.from_error(rust.String)
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB230"
    assert diagnostic.title == "Duplicate error conversion"
