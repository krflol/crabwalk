from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path, analyze_project_path
from crabwalk.compiler.ir import CrateCallIR, Effect, LetIR, ReturnIR
from crabwalk.compiler.types import ExternalType
from crabwalk.diagnostics import CrabwalkCompilationError


ADAPTER_SOURCE = """\
from crabwalk import rust

native = rust.crate("native-adapter", path="./native")
Counter = rust.extern_type(native, path="model::Counter")

@rust.extern(native, path="model::make_counter", effects=[rust.Pure])
def make_counter(value: rust.u64) -> Counter:
    ...

@rust.extern(native, path="model::counter_value", effects=[rust.Pure])
def counter_value(counter: rust.Ref[Counter]) -> rust.u64:
    pass

@rust.extern(native, path="apply_twice", effects=[rust.Pure])
def apply_twice(
    value: rust.u64,
    callback: rust.Closure[rust.u64, rust.u64],
) -> rust.u64:
    ...

@rust.fn
def adapted(value: rust.u64) -> rust.u64:
    counter: Counter = make_counter(value)
    current: rust.u64 = counter_value(counter)
    return apply_twice(current, lambda item: item + 1)
"""


def test_typed_crate_values_closures_and_effects_are_semantic(tmp_path: Path) -> None:
    source = tmp_path / "adapter.py"
    source.write_text(ADAPTER_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_adapter")
    function = ir.functions[0]

    assert len(ir.functions) == 1
    first = function.body[0]
    assert isinstance(first, LetIR)
    assert isinstance(first.type_ref, ExternalType)
    assert first.type_ref.render().endswith("::model::Counter")
    assert isinstance(first.value, CrateCallIR)
    assert first.value.adapter_name == "make_counter"
    assert first.value.declared_effects == ()
    returned = function.body[-1]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, CrateCallIR)
    assert returned.value.adapter_name == "apply_twice"
    assert Effect.OPAQUE_CRATE_CALL not in function.effects
    assert "::model::make_counter(value)" in generated.rust_source
    assert "|item| (item + 1u64)" in generated.rust_source


def test_unannotated_opaque_crate_values_cannot_escape_a_terminal_chain(
    tmp_path: Path,
) -> None:
    source = tmp_path / "opaque.py"
    source.write_text(
        """\
from crabwalk import rust
native = rust.crate("native-adapter", path="./native")

@rust.fn
def invalid() -> rust.u64:
    value = native.make_counter(1)
    return value.value()
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB222"
    assert "rust.extern_type/rust.extern" in (captured.value.diagnostics[0].help or "")


def test_unannotated_external_adapter_keeps_the_opaque_default(tmp_path: Path) -> None:
    source = tmp_path / "opaque_adapter.py"
    source.write_text(
        """\
from crabwalk import rust
native = rust.crate("native-adapter", path="./native")

@rust.extern(native, path="identity")
def identity(value: rust.u64) -> rust.u64:
    ...

@rust.fn
def call(value: rust.u64) -> rust.u64:
    return identity(value)
""",
        encoding="utf-8",
    )

    function = analyze_path(source).functions[0]
    assert Effect.OPAQUE_CRATE_CALL in function.effects
    assert Effect.MAY_PANIC in function.effects


def test_typed_adapter_types_and_functions_resolve_across_package_imports(
    tmp_path: Path,
) -> None:
    package = tmp_path / "adapter_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .kernel import adapted\n",
        encoding="utf-8",
    )
    (package / "adapters.py").write_text(
        """\
from crabwalk import rust

native = rust.crate("native-adapter", path="../native")
Counter = rust.extern_type(native, path="model::Counter")

@rust.extern(native, path="model::make_counter", effects=[rust.Pure])
def make_counter(value: rust.u64) -> Counter:
    ...

@rust.extern(native, path="model::counter_value", effects=[rust.Pure])
def counter_value(counter: rust.Ref[Counter]) -> rust.u64:
    ...
""",
        encoding="utf-8",
    )
    kernel = package / "kernel.py"
    kernel.write_text(
        """\
from crabwalk import rust
from .adapters import Counter, counter_value, make_counter

@rust.fn
def adapted(value: rust.u64) -> rust.u64:
    counter: Counter = make_counter(value)
    return counter_value(counter)
""",
        encoding="utf-8",
    )

    ir = analyze_project_path(kernel, "adapter_pkg.kernel")

    assert [function.qualified_name for function in ir.functions] == [
        "adapter_pkg.kernel.adapted"
    ]
    first = ir.functions[0].body[0]
    assert isinstance(first, LetIR)
    assert isinstance(first.type_ref, ExternalType)
    assert first.type_ref.source_name == "Counter"
    assert first.type_ref.render().endswith("::model::Counter")
