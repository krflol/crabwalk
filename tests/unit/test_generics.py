from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


GENERIC_SOURCE = """\
from crabwalk import rust

T = rust.typevar("T")
a = rust.lifetime("a")

@rust.generic(T, bounds=[rust.PartialOrd, rust.Copy])
def largest(values: rust.Ref[rust.Vec[T]]) -> T:
    index: rust.usize = 1
    largest_value: T = values[0]
    while index < values.len():
        candidate: T = values[index]
        if candidate > largest_value:
            largest_value = candidate
        index += 1
    return largest_value

@rust.generic(a)
def longest(left: rust.Borrow[a, rust.Str], right: rust.Borrow[a, rust.Str]) -> rust.Borrow[a, rust.Str]:
    if left.len() > right.len():
        return left
    return right

@rust.fn
def largest_u64() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([34, 50, 25, 100, 65])
    return largest(values)

@rust.fn
def longest_owned(left: rust.Str, right: rust.Str) -> rust.String:
    return rust.String(longest(left, right))
"""


def test_native_only_generic_function_is_inferred_and_monomorphized(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generics.py"
    source.write_text(GENERIC_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_generics")

    generic, lifetime_helper, wrapper, lifetime_wrapper = ir.functions
    assert generic.exported is False
    assert wrapper.exported is True
    assert generic.type_parameters[0].name == "T"
    assert generic.type_parameters[0].bounds == ("PartialOrd", "Copy")
    assert (
        "fn __cw_native_largest<T: PartialOrd + Copy>(values: &Vec<T>) -> T"
        in generated.rust_source
    )
    assert "fn largest(" not in generated.rust_source
    assert "__cw_native_largest(&values)" in generated.rust_source
    assert lifetime_helper.type_parameters[0].is_lifetime is True
    assert (
        "fn __cw_native_longest<'a>(left: &'a str, right: &'a str) -> &'a str"
        in generated.rust_source
    )
    assert lifetime_wrapper.exported is True
    assert "m.add_function(pyo3::wrap_pyfunction!(largest_u64, m)?)?;" in (
        generated.rust_source
    )
