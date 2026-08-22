from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path, analyze_project_path
from crabwalk.compiler.ir import TypeRef
from crabwalk.compiler.naming import owned_class_names
from crabwalk.compiler.validation import validate_package_ir
from crabwalk.diagnostics import CrabwalkCompilationError


def test_user_abs_domain_string_and_pyo3_binding_do_not_collide(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collisions.py"
    source.write_text(
        """\
from crabwalk import rust

pyo3 = rust.crate("regex", version="1")

@rust.struct
class String:
    value: rust.u64

@rust.fn
def abs(value: rust.i32) -> rust.i32:
    return value
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_collision_names")

    assert 'package = "pyo3"' in generated.cargo_toml
    assert not any(
        line.startswith("pyo3 =") for line in generated.cargo_toml.splitlines()
    )
    assert "extern crate cw_runtime_pyo3 as pyo3;" in generated.rust_source
    assert 'regex = { version = "1" }' in generated.cargo_toml
    assert f"extern crate regex as {ir.crates[0].binding};" in generated.rust_source
    assert 'link_name = "abs"' in generated.rust_source
    assert "fn abs(" not in generated.rust_source
    assert "struct String" not in generated.rust_source


def test_package_path_mangling_distinguishes_underscores_from_components(
    tmp_path: Path,
) -> None:
    package = tmp_path / "mangle_pkg"
    nested = package / "a"
    nested.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (nested / "__init__.py").write_text("", encoding="utf-8")
    body = """\
from crabwalk import rust

@rust.fn
def value() -> rust.u64:
    return 1
"""
    (package / "a__b.py").write_text(body, encoding="utf-8")
    (nested / "b.py").write_text(body, encoding="utf-8")

    ir = analyze_project_path(package)
    symbols = [function.rust_symbol for function in ir.functions]

    assert len(symbols) == len(set(symbols)) == 2


def test_owned_wrapper_mangling_is_structural() -> None:
    first = TypeRef("Vec", (TypeRef("A_B"),))
    second = TypeRef("Vec_A", (TypeRef("B"),))

    assert owned_class_names(first) != owned_class_names(second)


def test_pre_codegen_identifier_table_rejects_duplicate_ir_symbols(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplicates.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def first() -> rust.u64:
    return 1

@rust.fn
def second() -> rust.u64:
    return 2
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    duplicate = replace(ir.functions[1], symbol=ir.functions[0].rust_symbol)

    with pytest.raises(CrabwalkCompilationError) as captured:
        validate_package_ir(replace(ir, functions=(ir.functions[0], duplicate)))

    assert captured.value.diagnostics[0].code == "CRAB209"


def test_pre_codegen_identifier_table_rejects_duplicate_method_glue(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplicate_methods.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Counter:
    value: rust.u64

@rust.method(Counter, name="first")
def first(counter: rust.Ref[Counter]) -> rust.u64:
    return counter.value

@rust.method(Counter, name="second")
def second(counter: rust.Ref[Counter]) -> rust.u64:
    return counter.value
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    duplicate = replace(ir.functions[1], method_name=ir.functions[0].method_name)

    with pytest.raises(CrabwalkCompilationError) as captured:
        validate_package_ir(replace(ir, functions=(ir.functions[0], duplicate)))

    assert captured.value.diagnostics[0].code == "CRAB209"
    assert "method glue namespace" in str(captured.value)
