from __future__ import annotations

from array import array
from pathlib import Path

import pytest

from crabwalk.boundary import (
    AllocationKind,
    InputPolicy,
    OwnershipPolicy,
    boundary_codec,
    validate_boundary_input,
)
from crabwalk.compiler.capabilities import ContractKind, capability_contract
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.abi import BUFFER_ELEMENTS
from crabwalk.compiler.ir import Effect, TypeRef
from crabwalk.diagnostics import CrabwalkCompilationError


def _write_source(tmp_path: Path, text: str) -> Path:
    source = tmp_path / "buffer_demo.py"
    source.write_text(text, encoding="utf-8")
    return source


def test_buffer_signature_has_borrowed_codec_and_safe_generated_view(
    tmp_path: Path,
) -> None:
    source = _write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def total(values: rust.Buffer[rust.f64]) -> rust.f64:
    result: rust.f64 = 0.0
    for value in values.iter():
        result += value
    return result + values[0]
""",
    )

    ir = analyze_path(source)
    function = ir.functions[0]
    generated = generate_project(ir, "_crabwalk_buffer_demo")
    codec = boundary_codec(function.parameters[0].type_ref)

    assert function.parameters[0].type_ref.display() == "rust.Buffer[rust.f64]"
    assert function.parameters[0].type_ref.render() == "__CwBuffer<'_, f64>"
    assert Effect.BORROWED_BUFFER in function.effects
    assert codec.input_policy == InputPolicy.BUFFER
    assert codec.allocation == AllocationKind.BORROWED_BUFFER
    assert codec.ownership == OwnershipPolicy.SHARED_BORROW
    assert "values: &Bound<'_, PyAny>" in generated.rust_source
    assert "pyo3::buffer::PyUntypedBuffer::get(values)" in generated.rust_source
    assert "&'a [pyo3::buffer::ReadOnlyCell<T>]" in generated.rust_source
    assert ".item_count() == 0 { &[] } else" in generated.rust_source
    assert ".as_typed::<f64>()?.as_slice(" in generated.rust_source
    assert ".readonly()" in generated.rust_source
    assert ".get(0usize)" in generated.rust_source
    assert ".detach(" not in generated.rust_source


def test_buffer_preflight_precedes_owned_extraction(tmp_path: Path) -> None:
    source = _write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def combined(
    values: rust.Owned[rust.Vec[rust.u64]],
    samples: rust.Buffer[rust.f64],
) -> rust.usize:
    return values.len() + samples.len()
""",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_buffer_atomic")
    rust_source = generated.rust_source

    assert rust_source.index(".dimensions()") < rust_source.index("values.value.take()")
    assert rust_source.index(".readonly()") < rust_source.index("values.value.take()")
    assert rust_source.index(".is_c_contiguous()") < rust_source.index(
        "values.value.take()"
    )


def test_external_buffer_adapter_uses_a_safe_owned_slice_copy(tmp_path: Path) -> None:
    source = _write_source(
        tmp_path,
        """\
from crabwalk import rust

native = rust.crate("native-buffer", path="./native")

@rust.extern(native, path="byte_sum", effects=[rust.Pure])
def byte_sum(values: rust.Buffer[rust.u8]) -> rust.u64:
    ...

@rust.fn
def total(values: rust.Buffer[rust.u8]) -> rust.u64:
    return byte_sum(values)
""",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_buffer_adapter")

    assert "fn to_vec(&self) -> Vec<T>" in generated.rust_source
    assert "::byte_sum(&(values).to_vec())" in generated.rust_source


@capability_contract(
    "buffer.invalid-input-rejected",
    native=False,
    kind=ContractKind.NEGATIVE,
)
def test_buffer_runtime_preflight_rejects_copy_or_aliasing_hazards() -> None:
    type_ref = TypeRef("Buffer", (TypeRef("f64"),))
    values = array("d", [1.0, 2.0, 3.0, 4.0])
    readonly = memoryview(values).toreadonly()

    assert validate_boundary_input(readonly, type_ref) is readonly
    with pytest.raises(ValueError, match="read-only"):
        validate_boundary_input(values, type_ref)
    with pytest.raises(ValueError, match="C-contiguous"):
        validate_boundary_input(readonly[::2], type_ref)
    multidimensional = memoryview(bytes((1, 2, 3, 4))).cast("B", shape=(2, 2))
    with pytest.raises(ValueError, match="one-dimensional"):
        validate_boundary_input(
            multidimensional,
            TypeRef("Buffer", (TypeRef("u8"),)),
        )
    with pytest.raises(TypeError, match="incompatible with rust.f64"):
        validate_boundary_input(memoryview(array("q", [1, 2])).toreadonly(), type_ref)
    with pytest.raises(TypeError, match="buffer protocol"):
        validate_boundary_input([1.0, 2.0], type_ref)


@pytest.mark.parametrize("element", sorted(BUFFER_ELEMENTS))
def test_every_declared_buffer_element_generates_a_typed_nonempty_check(
    tmp_path: Path,
    element: str,
) -> None:
    source = _write_source(
        tmp_path,
        f"""\
from crabwalk import rust

@rust.fn
def length(values: rust.Buffer[rust.{element}]) -> rust.usize:
    return values.len()
""",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_buffer_element")

    assert "values: &Bound<'_, PyAny>" in generated.rust_source
    assert f"std::mem::size_of::<{element}>()" in generated.rust_source
    assert f".as_typed::<{element}>()?.as_slice(" in generated.rust_source


@pytest.mark.parametrize(
    ("annotation", "message"),
    (
        ("rust.Buffer[rust.String]", "Unsupported borrowed buffer element type"),
        ("rust.Buffer[rust.i128]", "Unsupported borrowed buffer element type"),
    ),
)
def test_buffer_rejects_unsupported_element_types_before_rustc(
    tmp_path: Path,
    annotation: str,
    message: str,
) -> None:
    source = _write_source(
        tmp_path,
        f"""\
from crabwalk import rust

@rust.fn
def invalid(values: {annotation}) -> rust.usize:
    return values.len()
""",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB228"
    assert captured.value.diagnostics[0].title == message


def test_buffer_is_top_level_input_only(tmp_path: Path) -> None:
    nested = _write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def invalid(values: rust.Tuple[rust.Buffer[rust.f64], rust.u64]) -> rust.u64:
    return values[1]
""",
    )
    with pytest.raises(CrabwalkCompilationError) as nested_error:
        analyze_path(nested)
    assert nested_error.value.diagnostics[0].code == "CRAB201"

    returned = _write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def invalid(values: rust.Buffer[rust.f64]) -> rust.Buffer[rust.f64]:
    return values
""",
    )
    with pytest.raises(CrabwalkCompilationError) as return_error:
        analyze_path(returned)
    assert return_error.value.diagnostics[0].code == "CRAB228"
    assert (
        return_error.value.diagnostics[0].title
        == "Borrowed buffer return is unsupported"
    )


@pytest.mark.parametrize("worker", ("spawn", "rayon"))
def test_buffer_capture_cannot_cross_threads(tmp_path: Path, worker: str) -> None:
    body = (
        """\
    handle: rust.ThreadHandle[rust.usize] = rust.spawn(lambda: values.len())
    return handle.join()
"""
        if worker == "spawn"
        else """\
    return rows.par_iter().map(lambda row: values[0]).collect_vec()
"""
    )
    extra_parameter = (
        "" if worker == "spawn" else ", rows: rust.Ref[rust.Vec[rust.f64]]"
    )
    return_type = "rust.usize" if worker == "spawn" else "rust.Vec[rust.f64]"
    crate = "" if worker == "spawn" else 'rayon = rust.crate("rayon", version="1")\n'
    source = _write_source(
        tmp_path,
        f"""\
from crabwalk import rust

{crate}
@rust.fn
def invalid(values: rust.Buffer[rust.f64]{extra_parameter}) -> {return_type}:
{body}
""",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), "_crabwalk_buffer_capture")

    assert captured.value.diagnostics[0].code == "CRAB229"
    assert (
        captured.value.diagnostics[0].title
        == "Borrowed Python buffer cannot enter a native worker"
    )
