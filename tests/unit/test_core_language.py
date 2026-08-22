from pathlib import Path

from crabwalk import rust
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import (
    ForRangeIR,
    LetIR,
    NativePrintlnIR,
    ReturnIR,
    WhileIR,
)


CORE_SOURCE = """\
from crabwalk import rust

@rust.fn
def sum_to(n: rust.u64) -> rust.u64:
    total: rust.u64 = 0
    for value in range(n):
        total += value
    return total

@rust.fn
def count_to(n: rust.u64) -> rust.u64:
    value: rust.u64 = 0
    while value < n:
        value += 1
    return value

@rust.fn
def between(n: rust.u64, low: rust.u64, high: rust.u64) -> rust.bool:
    return n >= low and n <= high

@rust.fn
def negate(n: rust.i64) -> rust.i64:
    return -n

@rust.fn
def ratio(x: rust.f64, y: rust.f64) -> rust.f64:
    return x / y

@rust.fn
def greet(name: rust.Str) -> rust.String:
    rust.println(name)
    return rust.String(name)

@rust.fn
def vector_len(n: rust.u64) -> rust.usize:
    values: rust.Vec[rust.u64] = rust.Vec([n, 1])
    values.push(2)
    return values.len()

@rust.fn
def maybe(n: rust.u64) -> rust.Option[rust.u64]:
    if n == 0:
        return None
    return rust.Some(n)

@rust.fn
def validate(n: rust.u64) -> rust.Result[rust.u64, rust.String]:
    if n == 0:
        return rust.Err("zero")
    return rust.Ok(n)

@rust.fn
def python_hello(name: rust.Str) -> rust.String:
    print(name)
    return rust.String(name)

@rust.fn
def call_python_hello(name: rust.Str) -> rust.String:
    return python_hello(name)
"""


def test_runtime_type_markers_support_generic_annotations() -> None:
    assert repr(rust.Vec[rust.u64]) == "rust.Vec[rust.u64]"
    assert (
        repr(rust.Result[rust.u64, rust.String]) == "rust.Result[rust.u64, rust.String]"
    )


def test_core_language_lowers_to_typed_ir_and_rust(tmp_path: Path) -> None:
    path = tmp_path / "core.py"
    path.write_text(CORE_SOURCE, encoding="utf-8")
    ir = analyze_path(path, "core")

    sum_to = ir.functions[0]
    assert isinstance(sum_to.body[0], LetIR)
    assert sum_to.body[0].mutable
    assert isinstance(sum_to.body[1], ForRangeIR)
    count_to = ir.functions[1]
    assert isinstance(count_to.body[1], WhileIR)
    greet = ir.functions[5]
    assert isinstance(greet.body[0].value, NativePrintlnIR)
    assert isinstance(greet.body[1], ReturnIR)

    generated = generate_project(ir, "_crabwalk_core_abc")
    assert "for value in 0u64..n {" in generated.rust_source
    assert "while (value < n) {" in generated.rust_source
    assert "let mut values: Vec<u64> = vec![n, 1u64];" in generated.rust_source
    assert 'println!("{}", name);' in generated.rust_source
    validate = next(
        function for function in ir.functions if function.name == "validate"
    )
    assert (
        f"fn {validate.rust_symbol}(n: u64) -> PyResult<u64>" in generated.rust_source
    )
    assert "Err(error) => Err(cw_runtime_pyo3::exceptions::PyRuntimeError" in (
        generated.rust_source
    )
    python_hello = ir.functions[-2]
    caller = ir.functions[-1]
    assert python_hello.python_boundary
    assert python_hello.effects == (
        "NativeRust",
        "ConversionBoundary",
        "PythonRuntime",
    )
    assert caller.python_boundary
    assert (
        f"fn __cw_native_{python_hello.rust_symbol}(name: &str) -> PyResult<String>"
        in (generated.rust_source)
    )
    assert f"return Ok(__cw_native_{python_hello.rust_symbol}(name)?);" in (
        generated.rust_source
    )
