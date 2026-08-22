from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import BinaryIR, Effect, MethodCallIR, ReturnIR, TraitCallIR
from crabwalk.compiler.validation import validate_package_ir
from crabwalk.diagnostics import CrabwalkCompilationError


@pytest.mark.parametrize("worker", ["spawn", "pool"])
def test_ir_validation_rejects_python_runtime_calls_inside_workers(
    tmp_path: Path,
    worker: str,
) -> None:
    statement = (
        "rust.spawn(lambda: report()).join()"
        if worker == "spawn"
        else (
            "pool: rust.ThreadPool = rust.ThreadPool(1)\n"
            "    pool.execute(lambda: report())\n"
            '    pool.finish().expect("worker failed")'
        )
    )
    source = tmp_path / f"worker_{worker}.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.fn
def report() -> None:
    print("worker")

@rust.fn
def invalid() -> None:
    {statement}
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), "_crabwalk_invalid_worker")

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB206"
    assert diagnostic.span is not None


def test_ir_validation_detects_missing_effect_annotation(tmp_path: Path) -> None:
    source = tmp_path / "effect_invariant.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid() -> None:
    rust.panic("boom")
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    broken = replace(ir, functions=(replace(ir.functions[0], effects=()),))

    with pytest.raises(AssertionError, match="missing MayPanic"):
        validate_package_ir(broken)


@pytest.mark.parametrize(
    ("rust_type", "expression", "removed", "expected"),
    [
        ("rust.i32", "rust.c_abs(value)", Effect.MAY_PANIC, "MayPanic"),
        (
            "rust.u64",
            "rust.unsafe_static_increment(value)",
            Effect.GLOBAL_MUTATION,
            "GlobalMutation",
        ),
    ],
)
def test_ir_validation_requires_safety_effects(
    tmp_path: Path,
    rust_type: str,
    expression: str,
    removed: Effect,
    expected: str,
) -> None:
    source = tmp_path / "safety_effect.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.fn
def safety(value: {rust_type}) -> {rust_type}:
    return {expression}
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    function = ir.functions[0]
    broken = replace(
        ir,
        functions=(
            replace(
                function,
                effects=tuple(
                    effect for effect in function.effects if effect != removed
                ),
            ),
        ),
    )

    with pytest.raises(AssertionError, match=f"missing {expected}"):
        validate_package_ir(broken)


def test_method_dispatch_propagates_python_runtime_effect_before_codegen(
    tmp_path: Path,
) -> None:
    source = tmp_path / "method_boundary.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Counter:
    value: rust.u64

@rust.method(Counter, name="read")
def read_counter(counter: rust.Ref[Counter]) -> rust.u64:
    print(counter.value)
    return counter.value

@rust.fn
def read_via_method() -> rust.u64:
    counter: Counter = Counter(value=7)
    return counter.read()
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    method = next(
        function for function in ir.functions if function.method_name == "read"
    )
    caller = next(
        function for function in ir.functions if function.name == "read_via_method"
    )
    assert Effect.PYTHON_RUNTIME in method.effects
    assert Effect.PYTHON_RUNTIME in caller.effects
    returned = caller.body[-1]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, MethodCallIR)
    assert returned.value.target_symbol == method.rust_symbol
    assert returned.value.dispatch_targets == (method.rust_symbol,)

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(ir, "_crabwalk_method_boundary")

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB207"
    assert diagnostic.span is not None
    assert "method" in diagnostic.message.lower()


@pytest.mark.parametrize(
    ("name", "source_text", "message_fragment"),
    [
        (
            "async",
            """\
from crabwalk import rust

@rust.async_fn
async def invalid_async() -> rust.u64:
    print(1)
    return 1
""",
            "async",
        ),
        (
            "iterator",
            """\
from crabwalk import rust

@rust.fn
def invalid_iterator(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.iter().map(lambda value: print(value)).count()
""",
            "closure",
        ),
        (
            "function_pointer",
            """\
from crabwalk import rust

@rust.fn
def report(value: rust.u64) -> rust.u64:
    print(value)
    return value

@rust.fn
def invalid_pointer(value: rust.u64) -> rust.u64:
    return rust.call_twice(report, value)
""",
            "function-pointer",
        ),
    ],
)
def test_python_runtime_boundary_is_rejected_in_non_result_contexts(
    tmp_path: Path,
    name: str,
    source_text: str,
    message_fragment: str,
) -> None:
    source = tmp_path / f"{name}_boundary.py"
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), f"_crabwalk_{name}_boundary")

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB207"
    assert diagnostic.span is not None
    assert message_fragment in f"{diagnostic.title} {diagnostic.message}".lower()


@pytest.mark.parametrize("dispatch_kind", ["trait", "operator"])
def test_trait_and_operator_dispatch_edges_propagate_effects(
    tmp_path: Path,
    dispatch_kind: str,
) -> None:
    declaration = (
        """\
Draw = rust.trait("Draw", draw=rust.u64)

@rust.struct
class Value:
    amount: rust.u64

@rust.impl(Draw, Value, name="draw")
def draw(value: rust.Ref[Value]) -> rust.u64:
    print(value.amount)
    return value.amount

@rust.fn
def dispatch() -> rust.u64:
    value: Value = Value(amount=1)
    return rust.trait_call(Draw, value, "draw")
"""
        if dispatch_kind == "trait"
        else """\
@rust.struct
class Value:
    amount: rust.u64

@rust.operator(Value, name="add")
def add(left: rust.Owned[Value], right: Value) -> Value:
    print(left.amount)
    return Value(amount=left.amount + right.amount)

@rust.fn
def dispatch() -> rust.u64:
    left: Value = Value(amount=1)
    right: Value = Value(amount=2)
    result: Value = left + right
    return result.amount
"""
    )
    source = tmp_path / f"{dispatch_kind}_dispatch.py"
    source.write_text(
        f"from crabwalk import rust\n\n{declaration}",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    implementation = next(
        function for function in ir.functions if function.method_for is not None
    )
    caller = next(function for function in ir.functions if function.name == "dispatch")
    assert Effect.PYTHON_RUNTIME in caller.effects
    expressions = tuple(
        statement.value
        for statement in caller.body
        if isinstance(statement, ReturnIR) and statement.value is not None
    )
    if dispatch_kind == "trait":
        expression = expressions[0]
        assert isinstance(expression, TraitCallIR)
        assert expression.target_symbol == implementation.rust_symbol
    else:
        binary = next(
            statement.value
            for statement in caller.body
            if hasattr(statement, "value") and isinstance(statement.value, BinaryIR)
        )
        assert binary.target_symbol == implementation.rust_symbol

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(ir, f"_crabwalk_{dispatch_kind}_dispatch")
    assert captured.value.diagnostics[0].code == "CRAB207"
