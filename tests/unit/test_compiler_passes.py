from __future__ import annotations

import ast
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
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import TypeRef
from crabwalk.compiler.ownership import Place, place_from_ast
from crabwalk.compiler.source import parse_source
from crabwalk.compiler.types import DomainType


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
