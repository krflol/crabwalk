from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import Effect
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
