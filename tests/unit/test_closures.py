from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import ClosureIR, MethodCallIR


CLOSURE_SOURCE = """\
from crabwalk import rust

@rust.fn
def transformed(minimum: rust.u64, offset: rust.u64) -> rust.Vec[rust.u64]:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4])
    return values.iter().map(lambda value: value + offset).filter(lambda value: value >= minimum).collect_vec()

@rust.fn
def shifted_sum(offset: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    return values.iter().map(lambda value: value + offset).sum()
"""


def test_lambdas_and_iterator_adapters_lower_to_typed_rust(tmp_path: Path) -> None:
    source = tmp_path / "closures.py"
    source.write_text(CLOSURE_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_closures")

    returned = ir.functions[0].body[1].value
    assert isinstance(returned, MethodCallIR)
    filtered = returned.receiver
    assert isinstance(filtered, MethodCallIR)
    assert isinstance(filtered.arguments[0], ClosureIR)
    assert filtered.arguments[0].borrowed_parameter is True
    assert ".iter().copied()" in generated.rust_source
    assert ".map(|value| (value + offset))" in generated.rust_source
    assert "let value = *__cw_item" in generated.rust_source
    assert ".collect::<Vec<_>>()" in generated.rust_source
    assert ".sum()" in generated.rust_source
