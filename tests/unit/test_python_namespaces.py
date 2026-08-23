from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.namespaces import (
    ENUM_MARKER_RESERVED_NAMES,
    OWNED_VALUE_RESERVED_NAMES,
)
from crabwalk.runtime import _RustOwnedValue
from crabwalk.rust import RustType


def test_owned_value_namespace_contract_matches_the_runtime_wrapper() -> None:
    assert frozenset(dir(_RustOwnedValue)) <= OWNED_VALUE_RESERVED_NAMES


def test_enum_marker_namespace_contract_matches_rust_type() -> None:
    marker = RustType("Status", python_name="Status", variants=("Ready",))

    assert frozenset(dir(marker)) <= ENUM_MARKER_RESERVED_NAMES


@pytest.mark.parametrize(
    "field_name",
    ["moved", "rust_type", "to_python", "_native", "_type_key"],
)
def test_struct_fields_cannot_shadow_owned_value_members(
    tmp_path: Path,
    field_name: str,
) -> None:
    source = tmp_path / "struct_wrapper_collision.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.struct
class Task:
    {field_name}: rust.u64
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB210"
    assert diagnostic.span is not None


@pytest.mark.parametrize(
    "variant_name",
    ["name", "arguments", "variants", "rust_key", "is_generic"],
)
def test_enum_variants_cannot_shadow_rust_type_members(
    tmp_path: Path,
    variant_name: str,
) -> None:
    source = tmp_path / "enum_marker_collision.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.enum
class Status:
    {variant_name} = rust.variant()
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB210"
    assert diagnostic.span is not None


@pytest.mark.parametrize("field_name", ["moved", "rust_type", "_native"])
def test_enum_payload_fields_cannot_shadow_owned_value_members(
    tmp_path: Path,
    field_name: str,
) -> None:
    source = tmp_path / "enum_wrapper_collision.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.enum
class Status:
    Ready = rust.variant({field_name}=rust.u64)
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB210"
    assert diagnostic.span is not None


def test_neighboring_nonconflicting_domain_names_remain_available(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nonconflicting_names.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Record:
    name: rust.String

@rust.enum
class Status:
    moved = rust.variant(name=rust.u64)
""",
        encoding="utf-8",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_python_namespaces")

    assert "pub name: String" in generated.rust_source
    assert "moved {\n        name: u64," in generated.rust_source
