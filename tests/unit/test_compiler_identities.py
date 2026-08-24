from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from crabwalk.compiler.emission import EmissionNames
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.symbols import (
    BindingIR,
    BindingId,
    Gensym,
    RustNamespace,
)
from crabwalk.compiler.validation import validate_package_ir
from crabwalk.diagnostics import (
    CrabwalkCompilationError,
    SourceSpan,
)


def _span() -> SourceSpan:
    return SourceSpan("identities.py", 1, 1, 1, 2)


def test_gensym_is_injective_within_each_rust_namespace() -> None:
    gensym = Gensym()

    first_value = gensym.bind("item", _span(), RustNamespace.VALUE)
    shadowed_value = gensym.bind("item", _span(), RustNamespace.VALUE)
    type_name = gensym.bind("item", _span(), RustNamespace.TYPE)
    macro_name = gensym.bind("item", _span(), RustNamespace.MACRO)
    lifetime_name = gensym.bind("item", _span(), RustNamespace.LIFETIME)

    assert first_value.rust_name == "item"
    assert shadowed_value.rust_name != first_value.rust_name
    assert type_name.rust_name == "item"
    assert macro_name.rust_name == "item"
    assert lifetime_name.rust_name == "item"
    assert set(RustNamespace) == {
        RustNamespace.VALUE,
        RustNamespace.TYPE,
        RustNamespace.MACRO,
        RustNamespace.LIFETIME,
        RustNamespace.MEMBER,
    }


def test_emission_allocator_reserves_semantic_bindings_recursively(
    tmp_path: Path,
) -> None:
    source = tmp_path / "reserved_emission_name.py"
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
    parameter = function.parameters[0]
    assert parameter.binding is not None
    reserved_name = "__cw_tmp_0_76616c7565"
    adversarial = BindingIR(
        BindingId(parameter.binding.identifier.value),
        parameter.binding.source_name,
        reserved_name,
        RustNamespace.VALUE,
        parameter.binding.span,
    )
    function = replace(
        function,
        parameters=(replace(parameter, binding=adversarial),),
    )

    allocated = EmissionNames.for_function(function).temporary("value")

    assert allocated != reserved_name
    assert allocated.startswith("__cw_tmp_1_")


def test_validation_rejects_conflicting_binding_identity_before_codegen(
    tmp_path: Path,
) -> None:
    source = tmp_path / "conflicting_binding_identity.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def add(left: rust.u64, right: rust.u64) -> rust.u64:
    return left + right
""",
        encoding="utf-8",
    )
    package = analyze_path(source)
    function = package.functions[0]
    left, right = function.parameters
    assert left.binding is not None
    assert right.binding is not None
    conflicting = replace(right.binding, rust_name=left.binding.rust_name)
    invalid_function = replace(
        function,
        parameters=(left, replace(right, binding=conflicting)),
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        validate_package_ir(replace(package, functions=(invalid_function,)))

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB209"
    assert diagnostic.span == right.span


def test_domain_member_source_and_rust_identities_are_separate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "domain_member_identities.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Record:
    gen: rust.u64

@rust.enum
class State:
    gen = rust.variant(rust.u64)
""",
        encoding="utf-8",
    )

    package = analyze_path(source)
    field = package.structs[0].fields[0]
    variant = package.enums[0].variants[0]
    generated = generate_project(package, "_crabwalk_domain_member_identities")

    assert field.name == "gen"
    assert field.rust_name != field.name
    assert variant.name == "gen"
    assert variant.rust_name != variant.name
    assert f"pub {field.rust_name}: u64" in generated.rust_source
    assert '#[getter("gen")]' in generated.rust_source
    assert f"{variant.rust_name}(u64)" in generated.rust_source
    assert '#[pyo3(name = "gen")]' in generated.rust_source
