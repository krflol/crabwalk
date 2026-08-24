from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from crabwalk.compiler.abi import (
    owned_vector_element_supported,
    python_return_boundary_supported,
    struct_field_type_supported,
)
from crabwalk.compiler.cargo_emission import (
    cargo_dependency_specification,
    render_cargo_toml,
)
from crabwalk.compiler.declarations import DeclarationIndex
from crabwalk.compiler.effects import propagate_effects, statement_calls
from crabwalk.compiler.emission import Writer
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import Effect, ReturnIR, TypeRef
from crabwalk.compiler.lowering.expressions import binary_operator, integer_fits
from crabwalk.compiler.lowering.patterns import rust_pattern_char
from crabwalk.compiler.lowering.statements import block_returns
from crabwalk.compiler.ownership import Place, place_from_ast
from crabwalk.compiler.rust_emission import write_native_function
from crabwalk.compiler.source import parse_source
from crabwalk.compiler.types import DomainType
from crabwalk.diagnostics import SourceSpan


def test_source_and_declaration_passes_preserve_static_boundaries(
    tmp_path: Path,
) -> None:
    source = tmp_path / "declarations.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Row:
    value: rust.u64

@rust.enum
class State:
    Ready = rust.variant()

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )

    parsed = parse_source(source)
    declarations = DeclarationIndex.discover(parsed.tree)

    assert parsed.path == source.resolve()
    assert len(declarations.functions) == 1
    assert len(declarations.structs) == 1
    assert len(declarations.enums) == 1


def test_place_pass_retains_nested_storage_root() -> None:
    expression = ast.parse("record.rows[0].status", mode="eval").body

    assert place_from_ast(expression) == Place(
        "record",
        ("field:rows", "index", "field:status"),
    )


def test_expression_statement_and_pattern_passes_are_independent() -> None:
    assert binary_operator(ast.Add()) == "add"
    assert binary_operator(ast.Pow()) is None
    assert integer_fits(255, TypeRef("u8"))
    assert not integer_fits(256, TypeRef("u8"))
    assert rust_pattern_char("\n") == "'\\n'"

    span = SourceSpan("pass.py", 1, 1, 1, 2)
    assert block_returns((ReturnIR(None, span),))


def test_abi_pass_uses_recursive_structured_type_policy() -> None:
    row = DomainType("cw_row", "example.Row")
    vector_of_rows = TypeRef("Vec", (row,))
    nested_bytes = TypeRef("Vec", (TypeRef("Vec", (TypeRef("u8"),)),))

    assert owned_vector_element_supported(
        row,
        {row.rust_name},
        allow_domain=True,
    )
    assert owned_vector_element_supported(
        nested_bytes.arguments[0],
        set(),
        allow_domain=False,
    )
    assert struct_field_type_supported(row, {row.rust_name})
    assert not python_return_boundary_supported(vector_of_rows)


def test_cargo_emission_and_fingerprint_spec_share_one_dependency_model(
    tmp_path: Path,
) -> None:
    source = tmp_path / "crate.py"
    source.write_text(
        """\
from crabwalk import rust

rayon = rust.crate("rayon", version="1.12.0", features=["web_spin_lock"])

@rust.fn
def workers() -> rust.usize:
    return rayon.current_num_threads()
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    manifest = render_cargo_toml(ir, "_crabwalk_pass_test")
    specification = cargo_dependency_specification(ir)
    binding = ir.crates[0].binding

    assert 'rayon = { version = "1.12.0", features = ["web_spin_lock"] }' in manifest
    assert specification["declared"] == [
        {
            "binding": binding,
            "cargo_key": "rayon",
            "package": "rayon",
            "version": "1.12.0",
            "features": ["web_spin_lock"],
            "path": None,
            "git": None,
            "rev": None,
        }
    ]


def test_effect_pass_propagates_python_runtime_across_call_edges(
    tmp_path: Path,
) -> None:
    source = tmp_path / "effects.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def leaf(value: rust.u64) -> rust.u64:
    print(value)
    return value

@rust.fn
def caller(value: rust.u64) -> rust.u64:
    return leaf(value)
""",
        encoding="utf-8",
    )
    package = analyze_path(source)
    reset = tuple(
        replace(function, effects=(), python_boundary=False)
        for function in package.functions
    )

    propagated = propagate_effects(reset)
    by_name = {function.name: function for function in propagated}

    assert statement_calls(by_name["caller"].body) == {by_name["leaf"].rust_symbol}
    assert Effect.PYTHON_RUNTIME in by_name["leaf"].effects
    assert Effect.PYTHON_RUNTIME in by_name["caller"].effects
    assert by_name["leaf"].python_boundary
    assert by_name["caller"].python_boundary


def test_rust_emission_pass_writes_one_typed_function(tmp_path: Path) -> None:
    source = tmp_path / "emission.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    function = analyze_path(source).functions[0]
    writer = Writer()

    write_native_function(writer, function, set())

    emitted = writer.render()
    assert f"fn __cw_native_{function.rust_symbol}" in emitted
    assert f"{function.parameters[0].rust_name}: u64" in emitted
    assert f"return {function.parameters[0].rust_name};" in emitted
