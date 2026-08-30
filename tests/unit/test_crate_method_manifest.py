from __future__ import annotations

from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import CrateCallIR, LetIR, ReturnIR, TryIR


CRATE_METHOD_SOURCE = """\
from crabwalk import rust

native = rust.crate("builder-adapter", path="./native")
Builder = rust.extern_type(native, path="Builder")
Batch = rust.extern_type(native, path="Batch")

@rust.extern(native, path="make_builder", effects=[rust.Pure])
def make_builder() -> Builder:
    ...

@rust.extern_method(
    native,
    Builder,
    path="builder_push",
    name="push",
    effects=[rust.Pure],
)
def builder_push(builder: rust.Mut[Builder], value: rust.u64) -> None:
    ...

@rust.extern_method(
    native,
    Builder,
    path="builder_finish",
    name="finish",
    effects=[rust.Pure],
)
def builder_finish(builder: rust.Owned[Builder]) -> rust.Result[Batch, rust.String]:
    ...

@rust.extern_method(
    native,
    Batch,
    path="batch_transform",
    name="transform",
    effects=[rust.Pure],
)
def batch_transform(
    batch: rust.Ref[Batch],
    callback: rust.Closure[rust.u64, rust.u64],
) -> rust.Vec[rust.u64]:
    ...

@rust.fn
def build_and_transform(value: rust.u64) -> rust.Result[
    rust.Vec[rust.u64],
    rust.String,
]:
    builder = make_builder()
    builder.push(value)
    builder.push(value + 1)
    batch = rust.try_(builder.finish())
    output: rust.Vec[rust.u64] = batch.transform(lambda item: item * 2)
    return rust.Ok(output)
"""


def test_external_builder_methods_have_typed_intermediates_and_errors(
    tmp_path: Path,
) -> None:
    source = tmp_path / "builder.py"
    source.write_text(CRATE_METHOD_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_builder")
    function = ir.functions[0]

    assert isinstance(function.body[0], LetIR)
    assert function.body[0].type_ref.display() == "Builder"
    assert isinstance(function.body[1].value, CrateCallIR)
    assert function.body[1].value.adapter_name == "builder_push"
    batch = function.body[3]
    assert isinstance(batch, LetIR)
    assert isinstance(batch.value, TryIR)
    assert isinstance(batch.value.value, CrateCallIR)
    assert batch.type_ref.display() == "Batch"
    returned = function.body[-1]
    assert isinstance(returned, ReturnIR)
    assert "::builder_push(&mut builder, value)" in generated.rust_source
    assert "::builder_finish(builder)" in generated.rust_source
    assert "::batch_transform(&batch, |item|" in generated.rust_source
    assert batch.type_ref.rust_name != "_"
