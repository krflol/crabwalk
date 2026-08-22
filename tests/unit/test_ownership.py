from pathlib import Path

import pytest

from crabwalk import rust
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import BorrowIR, CallIR, ExpressionStatementIR, ReturnIR
from crabwalk.compiler.naming import owned_class_names
from crabwalk.diagnostics import CrabwalkCompilationError


OWNERSHIP_SOURCE = """\
from crabwalk import rust

@rust.fn
def total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

@rust.fn
def append(values: rust.Mut[rust.Vec[rust.u64]], value: rust.u64) -> None:
    values.push(value)

@rust.fn
def consume(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

@rust.fn
def append_then_consume(
    values: rust.Owned[rust.Vec[rust.u64]], value: rust.u64
) -> rust.usize:
    append(values, value)
    return consume(values)
"""


def test_ownership_markers_are_runtime_types() -> None:
    vector = rust.Vec[rust.u64]
    assert repr(rust.Owned[vector]) == "rust.Owned[rust.Vec[rust.u64]]"
    assert repr(rust.Ref[vector]) == "rust.Ref[rust.Vec[rust.u64]]"
    assert repr(rust.Mut[vector]) == "rust.Mut[rust.Vec[rust.u64]]"
    with pytest.raises(TypeError, match="empty rust.Vec"):
        rust.Vec([])
    with pytest.raises(TypeError, match="homogeneous"):
        rust.Vec([1, "two"])


def test_ownership_lowers_to_real_rust_signatures_and_reborrows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ownership.py"
    path.write_text(OWNERSHIP_SOURCE, encoding="utf-8")

    ir = analyze_path(path, "ownership")
    generated = generate_project(ir, "_crabwalk_ownership_test")

    symbols = {function.name: function.rust_symbol for function in ir.functions}
    assert (
        f"fn __cw_native_{symbols['total']}(values: &Vec<u64>) -> usize"
        in generated.rust_source
    )
    assert (
        f"fn __cw_native_{symbols['append']}(mut values: &mut Vec<u64>, value: u64) -> ()"
        in generated.rust_source
    )
    assert (
        f"fn __cw_native_{symbols['consume']}(values: Vec<u64>) -> usize"
        in generated.rust_source
    )
    assert (
        f"fn __cw_native_{symbols['append_then_consume']}(mut values: Vec<u64>, value: u64)"
        in generated.rust_source
    )
    python_class, _ = owned_class_names(
        ir.functions[0].parameters[0].type_ref.underlying
    )
    assert f'#[pyclass(name = "{python_class}")]' in generated.rust_source
    assert "value: Option<Vec<u64>>" in generated.rust_source
    assert "values.value.take()" in generated.rust_source
    assert "values.value.as_ref()" in generated.rust_source
    assert "values.value.as_mut()" in generated.rust_source

    caller = ir.functions[-1]
    first = caller.body[0]
    assert isinstance(first, ExpressionStatementIR)
    assert isinstance(first.value, CallIR)
    assert isinstance(first.value.arguments[0], BorrowIR)
    assert first.value.arguments[0].kind == "mutable"
    second = caller.body[1]
    assert isinstance(second, ReturnIR)
    assert isinstance(second.value, CallIR)
    assert not isinstance(second.value.arguments[0], BorrowIR)


def test_rejects_ownership_wrapper_without_supported_concrete_vec(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsupported_ownership.py"
    path.write_text(
        """\
from crabwalk import rust

@rust.fn
def bad(value: rust.Ref[rust.String]) -> rust.usize:
    return 0
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(path)

    assert captured.value.diagnostics[0].code == "CRAB142"


def test_rejects_borrowed_return_type(tmp_path: Path) -> None:
    path = tmp_path / "borrowed_return.py"
    path.write_text(
        """\
from crabwalk import rust

@rust.fn
def bad(value: rust.Ref[rust.Vec[rust.u64]]) -> rust.Ref[rust.Vec[rust.u64]]:
    return value
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(path)

    assert captured.value.diagnostics[0].code == "CRAB141"


def test_rejects_implicit_vec_parameters_and_allows_vec_returns(
    tmp_path: Path,
) -> None:
    parameter = tmp_path / "implicit_parameter.py"
    parameter.write_text(
        """\
from crabwalk import rust

@rust.fn
def bad(values: rust.Vec[rust.u64]) -> rust.usize:
    return values.len()
""",
        encoding="utf-8",
    )
    with pytest.raises(CrabwalkCompilationError) as parameter_error:
        analyze_path(parameter)
    assert parameter_error.value.diagnostics[0].code == "CRAB201"

    returned = tmp_path / "implicit_return.py"
    returned.write_text(
        """\
from crabwalk import rust

@rust.fn
def bad() -> rust.Vec[rust.u64]:
    return rust.Vec([1, 2])
""",
        encoding="utf-8",
    )
    ir = analyze_path(returned)
    assert ir.functions[0].return_type.rust_name == "Vec"
    assert ir.functions[0].return_type.arguments[0].rust_name == "u64"
